import re
from typing import Callable, Optional, Union


class StringModifier:
    def evaluate(self, value: str) -> bool:
        raise NotImplementedError

class fuzzy(StringModifier):
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.regex = re.compile(pattern)
        
    def evaluate(self, value: str) -> bool:
        return self.regex.search(value) is not None

_demangle_func: Optional[Callable[[str], str]] = None
_demangle_resolved = False

def get_demangle_func() -> Optional[Callable[[str], str]]:
    global _demangle_func, _demangle_resolved
    if _demangle_resolved:
        return _demangle_func
        
    _demangle_resolved = True
    try:
        import cxxfilt
        _demangle_func = cxxfilt.demangle
    except ImportError:
        try:
            import itanium_demangler
            def _itanium_demangle(v: str) -> str:
                parsed = itanium_demangler.parse(v)
                return str(parsed) if parsed else v
            _demangle_func = _itanium_demangle
        except ImportError:
            def _identity_demangle(v: str) -> str:
                return v
            _demangle_func = _identity_demangle
             
    return _demangle_func

class demangle(StringModifier):
    def __init__(self, expected: Union[str, StringModifier]):
        self.expected = expected
        
    def evaluate(self, value: str) -> bool:
        demangler = get_demangle_func()
        if demangler is None:
            demangled = value
        else:
            try:
                demangled = demangler(value)
            except Exception:
                demangled = value
            
        if isinstance(self.expected, StringModifier):
            return self.expected.evaluate(demangled)
        return demangled == self.expected
