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


class CalculatorTool:
    name = "calculator"

    def run(self, text: str) -> dict:
        expression = extract_expression(text)
        if not expression:
            return {
                "ok": False,
                "error": "لم أستطع استخراج عملية حسابية واضحة. اكتب العملية مثل: 12 * (4 + 3).",
            }
        try:
            result = safe_calculate(expression)
        except Exception as exc:
            return {"ok": False, "expression": expression, "error": str(exc)}
        return {"ok": True, "expression": result.expression, "result": result.result}
