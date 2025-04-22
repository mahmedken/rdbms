from flask import Flask, render_template, request, jsonify
import os
import time
from pathlib import Path
from pyparsing import ParseException
from catalog import Catalog
from parser import SQLParser
from parser.validator import QueryValidator
from engine import Executor

app = Flask(__name__)

# Initialize database components
DATA_DIR = "./data"
Path(DATA_DIR).mkdir(exist_ok=True)
catalog = Catalog()
parser = SQLParser()
validator = QueryValidator(catalog)
executor = Executor(catalog, DATA_DIR)

@app.route('/')
def index():
    tables = catalog.list_tables()
    return render_template('index.html', tables=tables)

@app.route('/execute', methods=['POST'])
def execute_query():
    query = request.form.get('query', '')
    
    if not query.strip():
        return jsonify({'error': 'Query cannot be empty'})
    
    # Handle special commands
    if query.lower() == 'tables':
        tables = catalog.list_tables()
        return jsonify({'result': 'Available tables: ' + ', '.join(tables) if tables else 'No tables available.'})
    
    if query.lower().startswith('describe '):
        table_name = query.split(' ', 1)[1].strip()
        try:
            schema = catalog.get_schema(table_name)
            columns = [f"{col.name} ({col.type})" for col in schema.columns]
            result = f"Table: {schema.name}\nColumns:\n" + "\n".join(columns)
            if schema.primary_key:
                result += f"\nPrimary Key: {schema.primary_key}"
            if schema.indexes:
                result += f"\nIndexes: {', '.join(schema.indexes)}"
            return jsonify({'result': result})
        except Exception as e:
            return jsonify({'error': str(e)})
    
    # Process SQL query
    try:
        start_time = time.perf_counter()
        
        # First, parse the SQL syntax
        try:
            parsed_query = parser.parse(query)
        except ParseException as e:
            return jsonify({'error': f"Syntax error: {e}"})
        except Exception as e:
            return jsonify({'error': f"Error parsing query: {e}"})
            
        # Then, validate the semantics
        try:
            validator.validate(parsed_query)
        except ParseException as e:
            return jsonify({'error': f"Validation error: {e}"})
        except Exception as e:
            return jsonify({'error': f"Error validating query: {e}"})
        
        query_type = parsed_query.get('query_type') if isinstance(parsed_query, dict) else getattr(parsed_query, 'query_type', None)
        
        if query_type in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE_TABLE', 'DROP_TABLE', 'CREATE_INDEX', 'DROP_INDEX']:
            rows, elapsed = executor.run(parsed_query)
            
            # Format the results
            if not rows:
                return jsonify({'result': f"Query executed successfully (0 rows, {elapsed:.4f} seconds)"})
            
            # Format results similar to your _format_results method
            if hasattr(rows[0], 'keys'):
                columns = list(rows[0].keys())
            else:
                columns = [f"col{i}" for i in range(len(rows[0]))]
            
            formatted_rows = []
            for row in rows:
                if hasattr(row, 'get'):
                    formatted_row = {col: row.get(col, '') for col in columns}
                else:
                    formatted_row = {columns[i]: row[i] if i < len(row) else '' for i in range(len(columns))}
                formatted_rows.append(formatted_row)
            
            return jsonify({
                'columns': columns,
                'rows': formatted_rows,
                'count': len(rows),
                'elapsed': f"{elapsed:.4f} seconds"
            })
        else:
            return jsonify({'error': f"Unsupported query type: {query_type}"})
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
