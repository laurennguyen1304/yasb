using System.Globalization;

namespace ClaudeStatusBar;

/// <summary>
/// A tiny recursive-descent arithmetic evaluator for the calculator bar.
/// Supports + - * / % ^, unary minus, parentheses and decimal numbers with the
/// usual precedence. Returns false for empty, incomplete, or malformed input so
/// the UI can stay quiet while the user is still typing.
/// </summary>
internal static class ExpressionEvaluator
{
    public static bool TryEvaluate(string? input, out double result)
    {
        result = 0;
        if (string.IsNullOrWhiteSpace(input)) return false;

        try
        {
            var parser = new Parser(input);
            double v = parser.ParseExpression();
            if (!parser.AtEnd) return false;                 // trailing garbage
            if (double.IsNaN(v) || double.IsInfinity(v)) return false;
            result = v;
            return true;
        }
        catch
        {
            return false;
        }
    }

    // Grammar (highest precedence last):
    //   expr  := term  (('+' | '-') term)*
    //   term  := unary (('*' | '/' | '%') unary)*
    //   unary := ('+' | '-') unary | power
    //   power := primary ('^' unary)?          (right-associative)
    //   primary := number | '(' expr ')'
    private sealed class Parser
    {
        private readonly string _s;
        private int _i;

        public Parser(string s) => _s = s;

        public bool AtEnd
        {
            get { SkipWs(); return _i >= _s.Length; }
        }

        public double ParseExpression()
        {
            double v = ParseTerm();
            while (true)
            {
                if (Match('+')) v += ParseTerm();
                else if (Match('-')) v -= ParseTerm();
                else break;
            }
            return v;
        }

        private double ParseTerm()
        {
            double v = ParseUnary();
            while (true)
            {
                if (Match('*')) v *= ParseUnary();
                else if (Match('/')) { double d = ParseUnary(); if (d == 0) throw new DivideByZeroException(); v /= d; }
                else if (Match('%')) { double d = ParseUnary(); if (d == 0) throw new DivideByZeroException(); v %= d; }
                else break;
            }
            return v;
        }

        private double ParseUnary()
        {
            if (Match('+')) return ParseUnary();
            if (Match('-')) return -ParseUnary();
            return ParsePower();
        }

        private double ParsePower()
        {
            double b = ParsePrimary();
            if (Match('^')) return Math.Pow(b, ParseUnary());
            return b;
        }

        private double ParsePrimary()
        {
            if (Match('('))
            {
                double v = ParseExpression();
                if (!Match(')')) throw new FormatException("missing )");
                return v;
            }
            return ParseNumber();
        }

        private double ParseNumber()
        {
            SkipWs();
            int start = _i;
            while (_i < _s.Length && (char.IsDigit(_s[_i]) || _s[_i] == '.')) _i++;
            if (_i == start) throw new FormatException("number expected");
            return double.Parse(_s[start.._i], CultureInfo.InvariantCulture);
        }

        private void SkipWs()
        {
            while (_i < _s.Length && char.IsWhiteSpace(_s[_i])) _i++;
        }

        private bool Match(char c)
        {
            SkipWs();
            if (_i < _s.Length && _s[_i] == c) { _i++; return true; }
            return false;
        }
    }
}
