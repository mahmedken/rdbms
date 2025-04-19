from flask import Flask, request, render_template
from parser import SQLParser
from catalog import Catalog

app = Flask(__name__)

# initialize catalog and parser
catalog = Catalog()
parser = SQLParser(catalog)

@app.route('/', methods=['GET', 'POST'])
def query():
    result = None
    error = None
    if request.method == 'POST':
        user_query = request.form.get('query')
        try:
            # parse the SQL query using your parser
            parsed = parser.parse(user_query)
            result = f"Parse successful: {parsed}"
        except Exception as e:
            error = f"Parse error: {str(e)}"
    return render_template('index.html', result=result, error=error)

if __name__ == '__main__':
    app.run(debug=True)
