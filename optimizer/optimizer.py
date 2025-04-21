# optimizer.py

from typing import Dict, List, Tuple, Any, Set, Optional
import math
from pyparsing import ParseResults
from catalog import Catalog

class QueryOptimizer:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        
    def optimize(self, query):
        """Main entry point for query optimization"""
        # Only optimize SELECT queries
        if not hasattr(query, 'query_type') or query.query_type != 'SELECT':
            return query

        # Make a copy of the query to avoid modifying the original
        optimized_query = query.copy()

        # Optimize condition ordering if WHERE clause exists
        if hasattr(optimized_query, 'where') and optimized_query.where:
            # optimized_query.where = self.optimize_conditions(optimized_query.where, optimized_query.tables)
            optimized_query['where'] = self.optimize_conditions(optimized_query.where, optimized_query.tables)

        # Optimize join method selection if multiple tables
        if len(optimized_query.tables) > 1:
            join_method = self.select_join_method(optimized_query.tables)
            
            # Try dictionary-style access first
            try:
                optimized_query['join_method'] = join_method
            except (TypeError, AttributeError):
                # If dictionary-like access fails, try attribute assignment
                setattr(optimized_query, 'join_method', join_method)

        return optimized_query



    
    def optimize_conditions(self, where_clause, tables):
        """Optimize the ordering of conditions in WHERE clause"""
        # Extract the condition from WHERE clause if needed
        if isinstance(where_clause, ParseResults) and len(where_clause) >= 2 and where_clause[0] == 'WHERE':
            condition = where_clause[1]
        else:
            condition = where_clause
            
        # Optimize the condition
        optimized_condition = self._optimize_condition_tree(condition, tables)
        
        # Reconstruct WHERE clause if needed
        if isinstance(where_clause, ParseResults) and len(where_clause) >= 2 and where_clause[0] == 'WHERE':
            where_clause[1] = optimized_condition
            return where_clause
        else:
            return optimized_condition
    
    def _optimize_condition_tree(self, condition, tables):
        """Recursively optimize a condition tree"""
        if not isinstance(condition, ParseResults) or len(condition) < 3:
            return condition
            
        # Handle AND conditions (conjunctive)
        if condition[1].upper() == "AND":
            left = condition[0]
            right = condition[2]
            
            # Recursively optimize subconditions
            left_opt = self._optimize_condition_tree(left, tables)
            right_opt = self._optimize_condition_tree(right, tables)
            
            # Reorder based on selectivity (most selective first)
            left_sel = self._estimate_condition_selectivity(left_opt, tables)
            right_sel = self._estimate_condition_selectivity(right_opt, tables)
            
            if right_sel < left_sel:  # Lower selectivity means more selective
                # Swap left and right
                condition[0] = right_opt
                condition[2] = left_opt
            else:
                condition[0] = left_opt
                condition[2] = right_opt
                
        # Handle OR conditions (disjunctive)
        elif condition[1].upper() == "OR":
            left = condition[0]
            right = condition[2]
            
            # Recursively optimize subconditions
            left_opt = self._optimize_condition_tree(left, tables)
            right_opt = self._optimize_condition_tree(right, tables)
            
            # Reorder based on selectivity (least selective first for OR)
            left_sel = self._estimate_condition_selectivity(left_opt, tables)
            right_sel = self._estimate_condition_selectivity(right_opt, tables)
            
            if right_sel > left_sel:  # Higher selectivity first for OR
                # Swap left and right
                condition[0] = right_opt
                condition[2] = left_opt
            else:
                condition[0] = left_opt
                condition[2] = right_opt
                
        return condition
    
    def _estimate_condition_selectivity(self, condition, tables):
        """Estimate the selectivity of a condition (0.0 to 1.0)"""
        if not isinstance(condition, ParseResults) or len(condition) < 3:
            return 0.5  # Default selectivity for unknown conditions
            
        # Simple comparison operators
        if condition[1] in ("=", "!=", "<", ">", "<=", ">="):
            left = condition[0]
            op = condition[1]
            right = condition[2]
            
            # Equality has higher selectivity than inequality
            if op == "=":
                return 0.1  # Assume 10% selectivity for equality
            elif op in (">", "<", ">=", "<="):
                return 0.3  # Assume 30% selectivity for range conditions
            else:  # !=
                return 0.9  # Assume 90% selectivity for not equals
                
        # Logical operators
        elif condition[1].upper() in ("AND", "OR"):
            left_sel = self._estimate_condition_selectivity(condition[0], tables)
            right_sel = self._estimate_condition_selectivity(condition[2], tables)
            
            if condition[1].upper() == "AND":
                return left_sel * right_sel  # Combine selectivities for AND
            else:  # OR
                return left_sel + right_sel - (left_sel * right_sel)  # Combine selectivities for OR
                
        return 0.5  # Default selectivity
    
    def select_join_method(self, tables):
        """Select the optimal join method (Nested-Loop vs Sort-Merge)"""
        if len(tables) < 2:
            return None  # No join needed
            
        # Get table names
        left_table = tables[0].table[0].lower() if isinstance(tables[0].table, ParseResults) else tables[0].table.lower()
        right_table = tables[1].table[0].lower() if isinstance(tables[1].table, ParseResults) else tables[1].table.lower()
        
        # Calculate costs for both join methods
        nested_loop_cost = self._estimate_nested_loop_cost(left_table, right_table)
        sort_merge_cost = self._estimate_sort_merge_cost(left_table, right_table)
        
        # Choose the method with lower cost
        if nested_loop_cost <= sort_merge_cost:
            return "nested_loop"
        else:
            return "sort_merge"
    






    def _estimate_nested_loop_cost(self, left_table, right_table):
        """Estimate the cost of a nested-loop join"""
        # Get table sizes
        left_size = self._estimate_table_size(left_table)
        right_size = self._estimate_table_size(right_table)
        
        # For small tables, make nested loop very attractive
        if left_size <= 200 and right_size <= 200:
            return 1  # Very low cost for small tables
        
        # Basic cost model: B(R) + B(R) * B(S)
        left_blocks = max(1, left_size // 100)
        right_blocks = max(1, right_size // 100)
        return left_blocks + (left_blocks * right_blocks)

    def _estimate_sort_merge_cost(self, left_table, right_table):
        """Estimate the cost of a sort-merge join"""
        # Get table sizes
        left_size = self._estimate_table_size(left_table)
        right_size = self._estimate_table_size(right_table)
        
        # For small tables, make sort-merge less attractive
        if left_size <= 200 and right_size <= 200:
            return 100  # Higher cost for small tables
        
        # Basic cost model: Sort cost + Merge cost
        left_blocks = max(1, left_size // 100)
        right_blocks = max(1, right_size // 100)
        
        # Check if tables have indexes on join columns
        left_indexed = self._has_index(left_table)
        right_indexed = self._has_index(right_table)
        
        # If both tables are indexed, sorting cost is reduced
        if left_indexed and right_indexed:
            sort_cost = 0  # Already sorted
        else:
            # Simplified sort cost
            sort_cost = (left_blocks * math.log2(max(2, left_blocks))) + (right_blocks * math.log2(max(2, right_blocks)))
        
        merge_cost = left_blocks + right_blocks
        return sort_cost + merge_cost







    
    def _estimate_table_size(self, table_name):
        """Estimate the number of tuples in a table"""
        try:
            # In a real implementation, you would get this from statistics
            # For now, use a simple heuristic based on the table schema
            schema = self.catalog.get_schema(table_name)
            # Assume each table has at least 100 tuples
            return max(100, len(schema.columns) * 100)
        except Exception:
            return 100  # Default size if table not found
    
    def _has_index(self, table_name):
        """Check if a table has any indexes"""
        try:
            schema = self.catalog.get_schema(table_name)
            return len(schema.indexes) > 0
        except Exception:
            return False
