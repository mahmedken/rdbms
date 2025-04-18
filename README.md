simplified RDBMS in python.

## components to be implemented:
- system catalog
- parser
- storage manager
- engine
- optimizer
- tests

## implementation details:

### catalog/
- minimal yet complete implementation of the system catalog layer
- presists schema in memory between runs
- enforces relational integrity constraints (pk, fk, unique naming)
- ready for integration with the parser and execution engine
