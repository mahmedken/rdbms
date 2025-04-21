"""relation algebra operators
data flows from the leaves of the operator tree to the root (iterator/volcano model)
ref: https://15445.courses.cs.cmu.edu/fall2021/notes/11-queryexecution1.pdf"""
from __future__ import annotations

import itertools
from typing import Callable, Dict, Iterator, List, Tuple, Any, Optional
from collections import defaultdict

# a tuple is represented as a dict {"alias.col": value}
Row = Dict[str, object]

class Operator:
    """base operator interface"""
    def open(self): ... # initialize the operator
    def next(self) -> Row | None: ... # get the next tuple
    def close(self): ... # clean up the operator

class TableScan(Operator):
    def __init__(self, heap_file, alias: str):
        self.heap = heap_file
        self.alias = alias
        self._iter: Iterator[Tuple] | None = None

    def open(self):
        self._iter = self.heap.scan()

    def next(self):
        try:
            tup = next(self._iter)  # type: ignore[misc]
        except StopIteration:
            return None
        return {
            f"{self.alias}.{col.name}": val
            for col, val in zip(self.heap.schema.columns, tup)
        }

    def close(self):
        self._iter = None

class Selection(Operator):
    def __init__(self, child: Operator, predicate: Callable[[Row], bool]):
        self.child = child
        self.p = predicate

    def open(self):
        self.child.open()

    def next(self):
        while True:
            row = self.child.next()
            if row is None:
                return None
            if self.p(row):
                return row

    def close(self):
        self.child.close()

class Projection(Operator):
    def __init__(self, child: Operator, columns: List[str]):
        self.child = child
        self.cols = columns  # qualified names

    def open(self):
        self.child.open()

    def next(self):
        row = self.child.next()
        if row is None:
            return None
        if self.cols == ["*"]:
            return row
        return {col: row[col] for col in self.cols}

    def close(self):
        self.child.close()

# ─────────────────────────────────────────────────────────────────────
class NestedLoopJoin(Operator):
    """simple NLJ with join predicate referring to both sides."""

    def __init__(
        self,
        left: Operator,
        right: Operator,
        predicate: Callable[[Row], bool],
    ):
        self.left = left
        self.right = right
        self.pred = predicate
        self._outer_row: Row | None = None
        self._right_open = False

    def open(self):
        self.left.open()
        self.right.open()
        self._right_open = True
        self._outer_row = self.left.next()

    def next(self):
        while self._outer_row is not None:
            inner_row = self.right.next()
            if inner_row is None:
                # restart right and advance outer
                self.right.close()
                self._outer_row = self.left.next()
                if self._outer_row is None:
                    # no more outer rows, we're done
                    return None
                self.right.open()
                continue
                
            joined = {**self._outer_row, **inner_row}
            if self.pred(joined):
                return joined
        return None

    def close(self):
        self.left.close()
        if self._right_open:
            self.right.close()

# ─────────────────────────────────────────────────────────────────────
class Aggregation(Operator):
    """Single-column aggregation without grouping"""
    
    def __init__(self, child: Operator, agg_functions: Dict[str, Tuple[str, str]]):
        """
        Initialize the aggregation operator
        
        Args:
            child: The input operator
            agg_functions: Dict mapping output column name to (function, input_column)
                where function is one of: MIN, MAX, SUM, AVG, COUNT
        """
        self.child = child
        self.agg_functions = agg_functions
        self._result: Optional[Row] = None
        
    def open(self):
        self.child.open()
        
        # Initialize aggregation values
        aggregates: Dict[str, Any] = {}
        counts: Dict[str, int] = {}  # For AVG calculation
        
        # Process all input rows
        row_count = 0
        while True:
            row = self.child.next()
            if row is None:
                break
                
            row_count += 1
            
            # Apply aggregation functions to each column
            for output_col, (func, input_col) in self.agg_functions.items():
                # Handle COUNT(*) special case
                if func == "COUNT" and input_col == "*":
                    aggregates[output_col] = row_count
                    continue
                    
                # Skip NULL values (except for COUNT)
                if input_col not in row or row[input_col] is None:
                    if func == "COUNT":
                        aggregates[output_col] = aggregates.get(output_col, 0)
                    continue
                    
                value = row[input_col]
                
                # Apply the appropriate aggregation function
                if func == "MIN":
                    if output_col not in aggregates or value < aggregates[output_col]:
                        aggregates[output_col] = value
                        
                elif func == "MAX":
                    if output_col not in aggregates or value > aggregates[output_col]:
                        aggregates[output_col] = value
                        
                elif func == "SUM":
                    if not isinstance(value, (int, float)):
                        raise TypeError(f"Cannot apply SUM to non-numeric value: {value}")
                    aggregates[output_col] = aggregates.get(output_col, 0) + value
                    
                elif func == "AVG":
                    if not isinstance(value, (int, float)):
                        raise TypeError(f"Cannot apply AVG to non-numeric value: {value}")
                    # Track sum and count for average calculation
                    aggregates[output_col] = aggregates.get(output_col, 0) + value
                    counts[output_col] = counts.get(output_col, 0) + 1
                    
                elif func == "COUNT":
                    aggregates[output_col] = aggregates.get(output_col, 0) + 1
        
        # Finalize AVG calculations
        for output_col, (func, _) in self.agg_functions.items():
            if func == "AVG" and output_col in aggregates and counts[output_col] > 0:
                aggregates[output_col] = aggregates[output_col] / counts[output_col]
        
        # Handle empty result sets
        if row_count == 0:
            for output_col, (func, _) in self.agg_functions.items():
                if func == "COUNT":
                    aggregates[output_col] = 0
                else:
                    aggregates[output_col] = None
        
        self._result = aggregates
            
    def next(self):
        # For simple aggregation (no GROUP BY), we return a single row then None
        result = self._result
        self._result = None
        return result
        
    def close(self):
        self.child.close()

# ─────────────────────────────────────────────────────────────────────
# dml operators

class InsertOperator(Operator):
    """Insert values into a table"""
    
    def __init__(self, heap_file, values: Tuple):
        """
        Initialize the insert operator
        
        Args:
            heap_file: The target HeapFile
            values: Tuple of values to insert
        """
        self.heap = heap_file
        self.values = values
        self._executed = False
        self._result = None
        
    def open(self):
        if not self._executed:
            # Insert the values into the heap file
            self.heap.insert(*self.values)
            self._executed = True
            # Return a result indicating the insert was successful
            self._result = {"operation": "INSERT", "rows_affected": 1}
        
    def next(self):
        if self._result:
            result = self._result
            self._result = None
            return result
        return None
        
    def close(self):
        pass

class DeleteOperator(Operator):
    """Delete rows from a table"""
    
    def __init__(self, child: Operator, heap_file):
        """
        Initialize the delete operator
        
        Args:
            child: Operator that produces rows to delete (typically a Selection)
            heap_file: The target HeapFile
        """
        self.child = child
        self.heap = heap_file
        self._executed = False
        self._result = None
        
    def open(self):
        if not self._executed:
            self.child.open()
            count = 0
            # Collect all rows to delete
            rows_to_delete = []
            while True:
                row = self.child.next()
                if row is None:
                    break
                # Extract primary key for deletion
                pk_col = f"{self.heap.table}.{self.heap.schema.primary_key}"
                if pk_col in row:
                    rows_to_delete.append(row[pk_col])
                    count += 1
            
            # Delete all collected rows
            for pk in rows_to_delete:
                self.heap.delete(pk)
                
            self._executed = True
            self._result = {"operation": "DELETE", "rows_affected": count}
        
    def next(self):
        if self._result:
            result = self._result
            self._result = None
            return result
        return None
        
    def close(self):
        self.child.close()

class UpdateOperator(Operator):
    """Update rows in a table"""
    
    def __init__(self, child: Operator, heap_file, updates: Dict[str, Any]):
        """
        Initialize the update operator
        
        Args:
            child: Operator that produces rows to update (typically a Selection)
            heap_file: The target HeapFile
            updates: Dictionary mapping column names to new values
        """
        self.child = child
        self.heap = heap_file
        self.updates = updates
        self._executed = False
        self._result = None
        
    def open(self):
        if not self._executed:
            self.child.open()
            count = 0
            # Process all rows to update
            while True:
                row = self.child.next()
                if row is None:
                    break
                    
                # Get the primary key
                pk_col = f"{self.heap.table}.{self.heap.schema.primary_key}"
                if pk_col not in row:
                    continue
                    
                pk = row[pk_col]
                
                # Prepare the updated values
                # First, get the current row values
                current_values = {}
                for i, col in enumerate(self.heap.schema.columns):
                    col_name = f"{self.heap.table}.{col.name}"
                    if col_name in row:
                        current_values[col.name] = row[col_name]
                
                # Apply updates to the current values
                for col_name, new_value in self.updates.items():
                    if col_name in current_values:
                        current_values[col_name] = new_value
                
                # Convert updated values to a tuple in the correct order
                updated_values = tuple(current_values.get(col.name) for col in self.heap.schema.columns)
                
                # Update the row
                self.heap.update(pk, *updated_values)
                count += 1
            
            self._executed = True
            self._result = {"operation": "UPDATE", "rows_affected": count}
        
    def next(self):
        if self._result:
            result = self._result
            self._result = None
            return result
        return None
        
    def close(self):
        self.child.close()

# ─────────────────────────────────────────────────────────────────────
# Operators for query features

class Sort(Operator):
    """Sort operator that sorts tuples based on given criteria"""
    
    def __init__(self, child: Operator, sort_keys: List[Tuple[str, bool]]):
        """
        Initialize the sort operator
        
        Args:
            child: The input operator
            sort_keys: List of (column, is_ascending) pairs defining the sort order
        """
        self.child = child
        self.sort_keys = sort_keys
        self._sorted_rows: List[Row] = []
        self._index = 0
        
    def open(self):
        # Collect all rows from child
        self.child.open()
        self._sorted_rows = []
        while True:
            row = self.child.next()
            if row is None:
                break
            self._sorted_rows.append(row)

        
        # helper to create reverse sort keys
        def _get_reverse_key(value):
            """Create a key for descending order sort"""
            if value is None:
                return value
            if isinstance(value, (int, float)):
                return -value
            # for strings, return a key that will sort in reverse
            return tuple(reversed([ord(c) for c in str(value)]))
            
        # Sort the rows based on the sort keys
        self._sorted_rows.sort(key=lambda row: tuple(
            row.get(col) if asc else _get_reverse_key(row.get(col))
            for col, asc in self.sort_keys
        ))
        
        self._index = 0
        
    def next(self):
        if self._index >= len(self._sorted_rows):
            return None
        row = self._sorted_rows[self._index]
        self._index += 1
        return row
        
    def close(self):
        self._sorted_rows = []
        self._index = 0
        self.child.close()


class GroupBy(Operator):
    """Group By operator that groups tuples based on given columns"""
    
    def __init__(self, child: Operator, group_keys: List[str], agg_functions: Dict[str, Tuple[str, str]]):
        """
        Initialize the group by operator
        
        Args:
            child: The input operator
            group_keys: List of column names to group by
            agg_functions: Dict mapping output column name to (function, input_column)
                where function is one of: MIN, MAX, SUM, AVG, COUNT
        """
        self.child = child
        self.group_keys = group_keys
        self.agg_functions = agg_functions
        self._groups: List[Row] = []
        self._index = 0
        
    def open(self):
        self.child.open()
        
        # Collect all rows and group them
        groups = defaultdict(list)
        while True:
            row = self.child.next()
            if row is None:
                break
                
            # Create a key tuple from the group by columns
            group_key = tuple(row.get(key) for key in self.group_keys)
            groups[group_key].append(row)
        
        # Process each group to calculate aggregates
        self._groups = []
        for group_key, rows in groups.items():
            result_row = {}
            
            # Add group by columns to result
            for i, key in enumerate(self.group_keys):
                result_row[key] = group_key[i]
                
            # Apply aggregation functions to each group
            for output_col, (func, input_col) in self.agg_functions.items():
                # Handle COUNT(*) special case
                if func == "COUNT" and input_col == "*":
                    result_row[output_col] = len(rows)
                    continue
                
                # Initialize aggregation values
                aggregate = None
                count = 0  # For AVG calculation
                
                # Apply the appropriate aggregation function to all rows in the group
                for row in rows:
                    # Skip NULL values (except for COUNT)
                    if input_col not in row or row[input_col] is None:
                        if func == "COUNT":
                            result_row[output_col] = result_row.get(output_col, 0) + 1
                        continue
                    
                    value = row[input_col]
                    
                    # Apply the aggregation function
                    if func == "MIN":
                        if aggregate is None or value < aggregate:
                            aggregate = value
                    elif func == "MAX":
                        if aggregate is None or value > aggregate:
                            aggregate = value
                    elif func == "SUM":
                        if aggregate is None:
                            aggregate = 0
                        aggregate += value
                    elif func == "AVG":
                        if aggregate is None:
                            aggregate = 0
                        aggregate += value
                        count += 1
                    elif func == "COUNT":
                        if aggregate is None:
                            aggregate = 0
                        aggregate += 1
                
                # Finalize AVG calculation
                if func == "AVG" and count > 0:
                    aggregate = aggregate / count
                
                # Handle empty result sets
                if len(rows) == 0:
                    if func == "COUNT":
                        aggregate = 0
                    else:
                        aggregate = None
                        
                result_row[output_col] = aggregate
            
            self._groups.append(result_row)
            
        self._index = 0
        
    def next(self):
        if self._index >= len(self._groups):
            return None
        row = self._groups[self._index]
        self._index += 1
        return row
        
    def close(self):
        self._groups = []
        self._index = 0
        self.child.close()

class Having(Operator):
    """Having operator that filters groups based on a predicate"""
    
    def __init__(self, child: Operator, predicate: Callable[[Row], bool]):
        """
        Initialize the having operator
        
        Args:
            child: The input operator (typically a GroupBy)
            predicate: Function that takes a row and returns True if it should be included
        """
        self.child = child
        self.predicate = predicate
        
    def open(self):
        self.child.open()
        
    def next(self):
        while True:
            row = self.child.next()
            if row is None:
                return None
            if self.predicate(row):
                return row
        
    def close(self):
        self.child.close()

class Limit(Operator):
    """Limit operator that limits the number of tuples returned"""
    
    def __init__(self, child: Operator, limit: int):
        """
        Initialize the limit operator
        
        Args:
            child: The input operator
            limit: Maximum number of rows to return
        """
        self.child = child
        self.limit = limit
        self._count = 0
        
    def open(self):
        self.child.open()
        self._count = 0
        
    def next(self):
        if self._count >= self.limit:
            return None
        
        row = self.child.next()
        if row is None:
            return None
            
        self._count += 1
        return row
        
    def close(self):
        self.child.close()