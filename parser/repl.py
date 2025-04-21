#!/usr/bin/env python3

import os
import readline
import time
import sys
from pathlib import Path
from typing import List, Optional

from catalog import Catalog
from parser import SQLParser
from engine import Executor

class DatabaseREPL:
    """Interactive REPL for the custom database system."""
    
    def __init__(self, data_dir: str = "./data"):
        """Initialize the REPL with database components."""
        self.data_dir = data_dir
        self.history_file = os.path.expanduser("~/.db_repl_history")
        self.catalog = Catalog()
        self.parser = SQLParser(self.catalog)
        self.executor = Executor(self.catalog, self.data_dir)
        
        # create data directory if it doesn't exist
        Path(self.data_dir).mkdir(exist_ok=True)
        
        # setup readline with history
        self._setup_readline()
        
        # welcome message components
        self.welcome_message = [
            "Custom Database REPL - Interactive SQL Shell",
            f"Data directory: {self.data_dir}",
            f"Tables: {', '.join(self.catalog.list_tables()) or 'None'}",
            "Type 'help' for assistance or 'exit' to quit",
            ""
        ]
    
    def _setup_readline(self):
        """Configure readline with history support."""
        # load history file if it exists
        if os.path.exists(self.history_file):
            readline.read_history_file(self.history_file)
        
        # set tab completion
        readline.parse_and_bind("tab: complete")
        
        # custom completer for SQL keywords and table names
        readline.set_completer(self._completer)
    
    def _completer(self, text: str, state: int) -> Optional[str]:
        """Provide tab completion for SQL keywords and table names."""
        # SQL keywords for completion
        keywords = [
            "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING",
            "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM",
            "CREATE TABLE", "DROP TABLE", "CREATE INDEX", "DROP INDEX"
        ]
        
        # add table names to completion options
        tables = self.catalog.list_tables()
        
        # combine keywords and tables
        options = keywords + tables
        
        # filter options that match the current text
        matches = [opt for opt in options if opt.lower().startswith(text.lower())]
        
        # return the match at the current state or None if no match
        return matches[state] if state < len(matches) else None
    
    def _save_history(self):
        """Save command history to file."""
        readline.write_history_file(self.history_file)
    
    def _format_results(self, rows: List, elapsed: float) -> str:
        """Format query results for display."""
        if not rows:
            return f"Query executed successfully (0 rows, {elapsed:.4f} seconds)"
        
        # get column names from the first row
        if hasattr(rows[0], 'keys'):
            # if rows are dictionary-like
            columns = list(rows[0].keys())
        else:
            # if rows are tuples, use generic column names
            columns = [f"col{i}" for i in range(len(rows[0]))]
        
        # calculate column widths
        widths = [len(col) for col in columns]
        for row in rows:
            for i, col in enumerate(columns):
                if hasattr(row, 'get'):
                    # dictionary-like row
                    val = str(row.get(col, ''))
                else:
                    # tuple-like row
                    val = str(row[i] if i < len(row) else '')
                widths[i] = max(widths[i], len(val))
        
        # format the header
        header = " | ".join(f"{col:{widths[i]}}" for i, col in enumerate(columns))
        separator = "-+-".join("-" * width for width in widths)
        
        # format each row
        formatted_rows = []
        for row in rows:
            if hasattr(row, 'get'):
                # dictionary-like row
                formatted_row = " | ".join(
                    f"{str(row.get(col, '')):{widths[i]}}" 
                    for i, col in enumerate(columns)
                )
            else:
                # tuple-like row
                formatted_row = " | ".join(
                    f"{str(row[i] if i < len(row) else ''):{widths[i]}}" 
                    for i in range(len(columns))
                )
            formatted_rows.append(formatted_row)
        
        # combine all parts
        result = "\n".join([
            header,
            separator,
            *formatted_rows,
            f"{len(rows)} row(s) returned ({elapsed:.4f} seconds)"
        ])
        
        return result
    

    def _process_command(self, command: str) -> bool:
        """Process special commands and SQL queries."""
        command = command.strip()
        
        # handle empty input
        if not command:
            return True
            
        # handle special commands
        if command.lower() == 'exit' or command.lower() == 'quit':
            return False
        if command.lower() == 'help':
            self._show_help()
            return True
        if command.lower() == 'tables':
            tables = self.catalog.list_tables()
            if tables:
                print("Available tables:")
                for table in tables:
                    print(f" - {table}")
            else:
                print("No tables available.")
            return True
        if command.lower().startswith('describe '):
            table_name = command.split(' ', 1)[1].strip()
            try:
                schema = self.catalog.get_schema(table_name)
                print(f"Table: {schema.name}")
                print("Columns:")
                for col in schema.columns:
                    print(f" - {col.name} ({col.type})")
                if schema.primary_key:
                    print(f"Primary Key: {schema.primary_key}")
                if schema.indexes:
                    print(f"Indexes: {', '.join(schema.indexes)}")
            except Exception as e:
                print(f"Error: {e}")
            return True
            
        # process SQL query
        try:
            # Parse the SQL query
            start_time = time.perf_counter()
            parsed_query = self.parser.parse(command)
            
            # Check the query type to determine how to handle it
            query_type = parsed_query.get('query_type') if isinstance(parsed_query, dict) else getattr(parsed_query, 'query_type', None)
            
            # For DML/DQL statements, use the executor
            if query_type in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE_TABLE', 'DROP_TABLE', 'CREATE_INDEX', 'DROP_INDEX']:
                rows, elapsed = self.executor.run(parsed_query)
                print(self._format_results(rows, elapsed))
            else:
                print(f"REPL Unsupported query type: {query_type}")
                
        except Exception as e:
            print(f"Error: {e}")
        return True



    def _show_help(self):
        """Display help information."""
        help_text = """
Available commands:
  help                 - Show this help message
  exit, quit           - Exit the REPL
  tables               - List all tables
  describe <table>     - Show table schema

SQL Commands:
  SELECT ... FROM ...  - Query data
  INSERT INTO ...      - Insert data
  UPDATE ... SET ...   - Update data
  DELETE FROM ...      - Delete data
  CREATE TABLE ...     - Create a new table
  DROP TABLE ...       - Drop a table
  CREATE INDEX ...     - Create an index
  DROP INDEX ...       - Drop an index
        """
        print(help_text)
    
    def run(self):
        """Run the REPL main loop."""
        # display welcome message
        for line in self.welcome_message:
            print(line)
        
        # main REPL loop
        multiline_query = []
        try:
            while True:
                # determine prompt based on whether we're in multiline mode
                if multiline_query:
                    prompt = "... "
                else:
                    prompt = "SQL> "
                
                # get user input
                try:
                    line = input(prompt)
                except EOFError:
                    print("\nExiting...")
                    break
                
                # handle multiline queries
                if line.strip().endswith(';'):
                    # end of query
                    multiline_query.append(line.rstrip(';'))
                    full_query = ' '.join(multiline_query)
                    multiline_query = []
                    
                    # process the complete query
                    if not self._process_command(full_query):
                        break
                elif not line.strip() and multiline_query:
                    # empty line in multiline mode - execute the query
                    full_query = ' '.join(multiline_query)
                    multiline_query = []
                    
                    # process the complete query
                    if not self._process_command(full_query):
                        break
                elif line.strip():
                    # add to multiline query
                    multiline_query.append(line)
                else:
                    # empty line in single-line mode
                    continue
        
        finally:
            # save command history
            self._save_history()
            print("Goodbye!")

if __name__ == "__main__":
    # parse command-line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Interactive SQL REPL for custom database")
    parser.add_argument("--data-dir", default="./data", help="Directory for database files")
    args = parser.parse_args()
    
    # run the REPL
    repl = DatabaseREPL(data_dir=args.data_dir)
    repl.run()
