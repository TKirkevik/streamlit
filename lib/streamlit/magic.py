# Copyright 2019 Streamlit Inc. All rights reserved.
# -*- coding: utf-8 -*-

import ast
from streamlit import compatibility


def add_magic(code, script_path):
    """Modifies the code to support magic Streamlit commands.

    Parameters
    ----------
    code : str
        The Python code.
    script_path : str
        The path to the script file.

    Returns
    -------
    ast.Module
        The syntax tree for the code.

    """
    if compatibility.is_running_py3():
        # Pass script_path so we get pretty exceptions.
        tree = ast.parse(code, script_path, 'exec')
        return _modify_ast_subtree(tree, is_root=True)
    return code


def _modify_ast_subtree(tree, body_attr='body', is_root=False):
    """Parses magic commands and modifies the given AST (sub)tree."""

    body = getattr(tree, body_attr)

    for i, node in enumerate(body):
        node_type = type(node)

        # Parse the contents of functions and With statements
        if node_type is ast.FunctionDef or node_type is ast.With:
            body[i] = _modify_ast_subtree(node)

        # Parse the contents of try statements
        elif node_type is ast.Try:
            for j, inner_node in enumerate(node.handlers):
                node.handlers[j] = _modify_ast_subtree(inner_node)
            finally_node = _modify_ast_subtree(node, body_attr='finalbody')
            node.finalbody = finally_node.finalbody
            body[i] = _modify_ast_subtree(node)

        # Convert expression nodes to st.write
        elif node_type is ast.Expr:
            value = _get_st_write_from_expr(node, i, parent_type=type(tree))
            if value is not None:
                node.value = value

    if is_root:
        # Import Streamlit so we can use it in the new_value above.
        # IMPORTANT: This breaks Python 2 due to line numbering issues.
        _insert_import_statement(tree)

    ast.fix_missing_locations(tree)

    return tree


def _insert_import_statement(tree):
    """Insert Streamlit import statement at the top(ish) of the tree."""

    st_import = _build_st_import_statement()

    # If the 0th node is already an import statement, put the Streamlit
    # import below that, so we don't break "from __future__ import".
    if tree.body and type(tree.body[0]) in (ast.ImportFrom, ast.Import):
        tree.body.insert(1, st_import)

    # If the 0th node is a docstring and the 1st is an import statement,
    # put the Streamlit import below those, so we don't break "from
    # __future__ import".
    elif (len(tree.body) > 1
            and (
                type(tree.body[0]) is ast.Expr and
                type(tree.body[0].value) is ast.Str
            )
            and type(tree.body[1]) in (ast.ImportFrom, ast.Import)):
        tree.body.insert(2, st_import)

    else:
        tree.body.insert(0, st_import)


def _build_st_import_statement():
    """Build AST node for `import streamlit as __streamlit__`."""
    return ast.Import(
        names=[ast.alias(
            name='streamlit',
            asname='__streamlit__',
        )],
    )


def _build_st_write_call(nodes):
    """Build AST node for `__streamlit__._transparent_write(*nodes)`."""
    return ast.Call(
        func=ast.Attribute(
            attr='_transparent_write',
            value=ast.Name(id='__streamlit__', ctx=ast.Load()),
            ctx=ast.Load(),
        ),
        args=nodes,
        keywords=[],
        kwargs=None,
        starargs=None,
    )


def _get_st_write_from_expr(node, i, parent_type):
    # Don't change function calls
    if type(node.value) is ast.Call:
        return None

    # Don't change Docstring nodes
    if (i == 0 and type(node.value) is ast.Str
            and parent_type in (ast.FunctionDef, ast.Module)):
        return None

    # If tuple, call st.write on the 0th element (rather than the
    # whole tuple). This allows us to add a comma at the end of a statement
    # to turn it into an expression that should be st-written. Ex:
    # "np.random.randn(1000, 2),"
    if type(node.value) is ast.Tuple:
        args = node.value.elts
        st_write = _build_st_write_call(args)

    # st.write all strings.
    elif type(node.value) is ast.Str:
        args = [node.value]
        st_write = _build_st_write_call(args)

    # st.write all variables, and also print the variable's name.
    elif type(node.value) is ast.Name:
        args = [
            ast.Str(s='**%s**' % node.value.id),
            node.value
        ]
        st_write = _build_st_write_call(args)

    # st.write everything else
    else:
        args = [node.value]
        st_write = _build_st_write_call(args)

    return st_write