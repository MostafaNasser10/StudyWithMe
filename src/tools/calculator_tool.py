from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass


OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


@dataclass
class CalculatorResult:
    expression: str
    result: float | int


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("Unsupported calculator expression")


def safe_calculate(expression: str) -> CalculatorResult:
    cleaned = expression.strip().replace("^", "**")
    if not re.fullmatch(r"[0-9+\-*/().% \t]+|\d[\d+\-*/().% \t]*\*\*[\d+\-*/().% \t]*", cleaned):
        raise ValueError("Only numeric arithmetic expressions are allowed.")
    tree = ast.parse(cleaned, mode="eval")
    result = _eval_node(tree)
    return CalculatorResult(expression=expression, result=result)


def extract_expression(text: str) -> str | None:
    candidates = re.findall(r"[-+*/().%^ 0-9]{3,}", text)
    candidates = [candidate.strip() for candidate in candidates if any(char.isdigit() for char in candidate)]
    return max(candidates, key=len) if candidates else None


def calculation_needed(text: str) -> bool:
    lowered = text.lower()
    keywords = ["calculate", "compute", "sum", "average", "احسب", "حساب", "ناتج", "متوسط"]
    return any(keyword in lowered for keyword in keywords) or bool(extract_expression(text))

