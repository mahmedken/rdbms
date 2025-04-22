#!/usr/bin/env python3

import os
import readline
import time
import sys
from pathlib import Path
from typing import List, Optional, Generator, Tuple, Any

from pyparsing import ParseException
from catalog import Catalog, UnknownTableError, CatalogError, IndexError_
from parser import SQLParser
from validator import QueryValidator
from engine import Executor
from storage.heap_file import HeapFile # Added import

class DatabaseREPLDemo:
    """Interactive REPL with commands to load/delete demo relations."""
    
    DEMO_RELATIONS = {
        "demo_1k_seq":    (1000,       lambda i: (i, i)),
        "demo_1k_const":  (1000,       lambda i: (i, 1)),
        "demo_100k_seq":  (100_000,    lambda i: (i, i)),
        "demo_100k_const":(100_000,    lambda i: (i, 1)),
        "demo_1m_seq":    (1_000_000,  lambda i: (i, i)),
        "demo_1m_const":  (1_000_000,  lambda i: (i, 1)),
    }
    DEMO_TABLE_NAMES = list(DEMO_RELATIONS.keys())

    def __init__(self, data_dir: str = "./data"):
        """Initialize the REPL with database components."""
        self.data_dir = data_dir
        self.history_file = os.path.expanduser("~/.db_repl_demo_history") # Separate history
        self.catalog = Catalog()
        self.parser = SQLParser()
        self.validator = QueryValidator(self.catalog)
        self.executor = Executor(self.catalog, self.data_dir)
        
        # create data directory if it doesn't exist
        Path(self.data_dir).mkdir(exist_ok=True)
        
        # setup readline with history
        self._setup_readline()
        
        # welcome message components
        self.welcome_message = [
            "Custom Database REPL - Demo Version", # Updated welcome
            f"Data directory: {self.data_dir}",
            f"Tables: {', '.join(self.catalog.list_tables()) or 'None'}",
            "Type 'help' for assistance or 'exit' to quit",
            "Demo commands: 'load demo relations', 'delete demo relations'", # Added hint
            ""
        ]
    
    def _setup_readline(self):
        """Configure readline with history support."""
        if os.path.exists(self.history_file):
            try:
                readline.read_history_file(self.history_file)
            except Exception as e:
                print(f"Warning: Could not load history file: {e}")
        
        readline.parse_and_bind("tab: complete")
        readline.set_completer(self._completer)
    
    def _completer(self, text: str, state: int) -> Optional[str]:
        """Provide tab completion for SQL keywords, table names, and demo commands."""
        keywords = [
            "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING",
            "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM",
            "CREATE TABLE", "DROP TABLE", "CREATE INDEX", "DROP INDEX",
            "load demo relations", "delete demo relations", # Added demo commands
            "help", "exit", "quit", "tables", "describe"
        ]
        
        tables = self.catalog.list_tables()
        options = keywords + tables
        matches = sorted([opt for opt in options if opt.lower().startswith(text.lower())])
        
        return matches[state] if state < len(matches) else None
    
    def _save_history(self):
        """Save command history to file."""
        try:
            readline.write_history_file(self.history_file)
        except Exception as e:
             print(f"Warning: Could not save history file: {e}")

    # _format_results remains the same as in repl.py
    def _format_results(self, rows: List, elapsed: float) -> str:
        """Format query results for display."""
        if not rows:
            # Check for message rows from DDL/DML operations
            if isinstance(rows, list) and len(rows) == 0: # Empty result set from SELECT
                 return f"Query executed successfully (0 rows, {elapsed:.4f} seconds)"
            # Handle cases where executor returns a non-list or specific messages
            # This part might need adjustment based on exact executor return types for DML/DDL
            return f"Operation completed ({elapsed:.4f} seconds)" 

        # Special handling for single message rows often returned by DML/DDL
        if len(rows) == 1 and isinstance(rows[0], dict) and "message" in rows[0] and len(rows[0]) == 1:
            return f"{rows[0]['message']} ({elapsed:.4f} seconds)"
        if len(rows) == 1 and isinstance(rows[0], dict) and "operation" in rows[0] and "rows_affected" in rows[0]:
             op_info = rows[0]
             msg = f"{op_info['operation']} completed, {op_info['rows_affected']} rows affected"
             if "error" in op_info:
                 msg += f", Error: {op_info['error']}"
             return f"{msg} ({elapsed:.4f} seconds)"

        # Formatting for SELECT results
        if hasattr(rows[0], 'keys'):
            columns = list(rows[0].keys())
        else:
            columns = [f"col{i}" for i in range(len(rows[0]))]
        
        widths = [len(col) for col in columns]
        for row in rows:
            for i, col in enumerate(columns):
                if hasattr(row, 'get'):
                    val = str(row.get(col, ''))
                else:
                    val = str(row[i] if i < len(row) else '')
                widths[i] = max(widths[i], len(val))
        
        header = " | ".join(f"{col:{widths[i]}}" for i, col in enumerate(columns))
        separator = "-+-".join("-" * width for width in widths)
        
        formatted_rows = []
        for row in rows:
            if hasattr(row, 'get'):
                formatted_row = " | ".join(
                    f"{str(row.get(col, '')):{widths[i]}}" 
                    for i, col in enumerate(columns)
                )
            else:
                formatted_row = " | ".join(
                    f"{str(row[i] if i < len(row) else ''):{widths[i]}}" 
                    for i in range(len(columns))
                )
            formatted_rows.append(formatted_row)
        
        result = "\n".join([
            header,
            separator,
            *formatted_rows,
            f"\n{len(rows)} row(s) returned ({elapsed:.4f} seconds)"
        ])
        
        return result

    def _process_command(self, command: str) -> bool:
        """Process special commands and SQL queries."""
        command = command.strip()
        if not command: return True # Continue on empty input
            
        cmd_lower = command.lower()

        if cmd_lower == 'exit' or cmd_lower == 'quit': return False
        if cmd_lower == 'help': self._show_help(); return True
        if cmd_lower == 'tables':
            tables = self.catalog.list_tables()
            print("Available tables:\n" + "\n".join(f" - {t}" for t in tables) if tables else "No tables available.")
            return True
        if cmd_lower == 'load demo relations':
            self._load_demo_relations()
            return True
        if cmd_lower == 'delete demo relations':
            self._delete_demo_relations()
            return True
            
        if cmd_lower.startswith('describe '):
            table_name = command.split(' ', 1)[1].strip()
            try:
                schema = self.catalog.get_schema(table_name)
                print(f"Table: {schema.name}")
                print("Columns:")
                for col in schema.columns: print(f" - {col.name} ({col.type})")
                if schema.primary_key: print(f"Primary Key: {schema.primary_key}")
                # Also show FKs if implemented in schema display
                if hasattr(schema, 'foreign_keys') and schema.foreign_keys:
                     print("Foreign Keys:")
                     for loc_col, (ref_tbl, ref_col) in schema.foreign_keys.items():
                         print(f" - {loc_col} REFERENCES {ref_tbl}({ref_col})")
                if schema.indexes: print(f"Indexes: {', '.join(schema.indexes)}")
            except Exception as e: print(f"Error describing table {table_name}: {e}")
            return True
            
        # --- Process as SQL query ---
        try:
            parsed_query = self.parser.parse(command)
            self.validator.validate(parsed_query)
            rows, elapsed = self.executor.run(parsed_query)
            print(self._format_results(rows, elapsed))
        except (ParseException, ValueError, TypeError, CatalogError, IndexError_, RuntimeError) as e:
            print(f"Error: {e}")
        except Exception as e:
            # Catch unexpected errors
            print(f"An unexpected error occurred: {e}")
            import traceback
            traceback.print_exc() # Print stack trace for debugging
        return True

    def _load_single_relation(self, table_name: str, num_tuples: int, generator_func: callable, batch_size: int = 50000):
        """Creates and populates a single demo table."""
        print(f"\nProcessing relation: {table_name} ({num_tuples:,} tuples)")
        create_sql = f"CREATE TABLE {table_name} (id INT, value INT, PRIMARY KEY(id))"
        
        # 1. Create Table
        try:
            print(f"  Creating table {table_name}...")
            parsed_query = self.parser.parse(create_sql)
            self.validator.validate(parsed_query)
            rows, elapsed = self.executor.run(parsed_query)
            print(f"  {rows[0]['message']} ({elapsed:.3f}s)")
        except Exception as e:
             # Check if it's a "table already exists" error - allow continuing if so
             if "already exists" in str(e).lower():
                  print(f"  Table {table_name} already exists, skipping creation.")
             else:
                  print(f"  Error creating table {table_name}: {e}. Aborting load for this table.")
                  return # Stop processing this table

        # 2. Insert Data in Batches
        print(f"  Inserting {num_tuples:,} rows (batch size: {batch_size:,})...")
        heap_file = None
        total_inserted = 0
        start_insert_time = time.perf_counter()
        try:
            heap_file = HeapFile(self.catalog, self.data_dir, table_name)
            current_batch: List[Tuple] = []
            num_batches = (num_tuples + batch_size - 1) // batch_size

            for i in range(1, num_tuples + 1):
                current_batch.append(generator_func(i))
                
                if len(current_batch) == batch_size or i == num_tuples:
                    batch_num = (i + batch_size -1) // batch_size
                    batch_start_time = time.perf_counter()
                    print(f"    Inserting batch {batch_num}/{num_batches} ({len(current_batch):,} rows)...", end='', flush=True)
                    
                    inserted_in_batch = heap_file.insert(current_batch) # Use unified insert
                    total_inserted += inserted_in_batch
                    
                    batch_elapsed = time.perf_counter() - batch_start_time
                    print(f" Done ({batch_elapsed:.3f}s)")
                    current_batch = [] # Clear batch

            end_insert_time = time.perf_counter()
            total_insert_elapsed = end_insert_time - start_insert_time
            print(f"  Finished inserting {total_inserted:,} rows into {table_name} in {total_insert_elapsed:.3f}s.")

        except (ValueError, TypeError, RuntimeError) as e:
            print(f"\n  Error during batch insert for {table_name}: {e}")
            print(f"  {total_inserted:,} rows may have been inserted before the error.")
        except Exception as e:
             print(f"\n  An unexpected error occurred during insertion for {table_name}: {e}")
             import traceback
             traceback.print_exc()

    def _load_demo_relations(self):
        """Loads all predefined demo relations."""
        print("Starting to load demo relations...")
        overall_start_time = time.perf_counter()
        
        for name, (size, gen_func) in self.DEMO_RELATIONS.items():
             self._load_single_relation(name, size, gen_func)
             
        overall_elapsed = time.perf_counter() - overall_start_time
        print(f"\nFinished loading all demo relations in {overall_elapsed:.3f}s.")
        # Update table list in welcome message after loading
        self.welcome_message[2] = f"Tables: {', '.join(self.catalog.list_tables()) or 'None'}"


    def _delete_demo_relations(self):
        """Deletes all predefined demo relations."""
        print("Starting to delete demo relations...")
        overall_start_time = time.perf_counter()
        deleted_count = 0
        skipped_count = 0

        for table_name in self.DEMO_TABLE_NAMES:
            print(f"  Attempting to drop table {table_name}...", end='', flush=True)
            drop_sql = f"DROP TABLE {table_name}"
            try:
                 # Check if table exists first to avoid validation errors
                 self.catalog.get_schema(table_name) # Raises UnknownTableError if not found

                 # If it exists, parse and execute drop
                 parsed_query = self.parser.parse(drop_sql)
                 # Validation is simple for DROP, but we can include it
                 # self.validator.validate(parsed_query) 
                 rows, elapsed = self.executor.run(parsed_query)
                 print(f" Dropped ({elapsed:.3f}s)")
                 deleted_count += 1
            except UnknownTableError:
                 print(" Does not exist, skipping.")
                 skipped_count += 1
            except Exception as e:
                 print(f" Error: {e}")

        overall_elapsed = time.perf_counter() - overall_start_time
        print(f"\nFinished deleting demo relations in {overall_elapsed:.3f}s. ({deleted_count} dropped, {skipped_count} skipped)")
         # Update table list in welcome message after deleting
        self.welcome_message[2] = f"Tables: {', '.join(self.catalog.list_tables()) or 'None'}"


    def _show_help(self):
        """Display help information."""
        help_text = """
Available commands:
  help                 - Show this help message
  exit, quit           - Exit the REPL
  tables               - List all tables
  describe <table>     - Show table schema
  load demo relations  - Create and populate large demo tables
  delete demo relations- Drop the demo tables

SQL Commands:
  Standard SQL for SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, DROP TABLE, etc.
  Use ';' to end multi-line queries or press Enter on an empty line.
        """
        print(help_text)
    
    # run method remains largely the same as in repl.py
    def run(self):
        """Run the REPL main loop."""
        for line in self.welcome_message: print(line)
        
        multiline_query = []
        try:
            while True:
                prompt = "... " if multiline_query else "DemoSQL> " # Changed prompt
                try: line = input(prompt)
                except EOFError: print("\nExiting..."); break
                except KeyboardInterrupt: print("\nType 'exit' or press Ctrl+D to exit."); multiline_query = []; continue # Clear query on Ctrl+C
                    
                stripped_line = line.strip()
                
                if stripped_line.endswith(';') and not stripped_line.startswith('--'): # Handle multi-line end
                    multiline_query.append(stripped_line.rstrip(';'))
                    full_query = ' '.join(multiline_query)
                    multiline_query = []
                    if not self._process_command(full_query): break
                elif not stripped_line and multiline_query: # Handle multi-line execute on empty line
                    full_query = ' '.join(multiline_query)
                    multiline_query = []
                    if not self._process_command(full_query): break
                elif stripped_line and not stripped_line.startswith('--'): # Continue multi-line or start single line
                     multiline_query.append(line) # Keep original spacing if multi-line
                     # If it's the start of a potential single line command, check if it's a special one immediately
                     if len(multiline_query) == 1 and not any(multiline_query[0].lower().startswith(kw) for kw in ["select", "insert", "update", "delete", "create", "drop"]):
                          cmd_check = multiline_query[0].strip()
                          is_special = False
                          if cmd_check.lower() in ['help', 'exit', 'quit', 'tables', 'load demo relations', 'delete demo relations'] or cmd_check.lower().startswith('describe '):
                                is_special = True
                                if not self._process_command(cmd_check): break
                                multiline_query = [] # Reset if it was a special command
                          # If not special, wait for semicolon or empty line
                # Handle single-line SQL that might not need a semicolon (though standard SQL usually does)
                # We primarily rely on the semicolon or empty line logic above now.
                # Add handling for simple comments
                elif stripped_line.startswith('--'):
                     continue # Ignore comment lines
                elif not stripped_line and not multiline_query: # Empty line when not in multi-line
                    continue
        
        finally:
            self._save_history()
            print("Goodbye!")

if __name__ == "__main__":
    import argparse
    parser_arg = argparse.ArgumentParser(description="Interactive SQL REPL for custom database (Demo Version)")
    parser_arg.add_argument("--data-dir", default="./data_demo", help="Directory for demo database files (default: ./data_demo)") # Changed default dir
    args = parser_arg.parse_args()
    
    repl_instance = DatabaseREPLDemo(data_dir=args.data_dir)
    repl_instance.run()