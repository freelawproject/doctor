import datetime
from decimal import Decimal

import six


class BTEUnicodeDecodeError(UnicodeDecodeError):
    def __init__(self, obj, *args):
        self.obj = obj
        UnicodeDecodeError.__init__(self, *args)

    def __str__(self):
        original = UnicodeDecodeError.__str__(self)
        return "%s. You passed in %r (%s)" % (
            original,
            self.obj,
            type(self.obj),
        )


def force_bytes(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Similar to smart_bytes, except that lazy instances are resolved to
    strings, rather than kept as lazy objects.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    # Handle the common case first for performance reasons.
    if isinstance(s, bytes):
        if encoding == "utf-8":
            return s
        else:
            return s.decode("utf-8", errors).encode(encoding, errors)
    if strings_only and is_protected_type(s):
        return s
    if isinstance(s, six.memoryview):
        return bytes(s)
    if isinstance(s, Promise):
        return six.text_type(s).encode(encoding, errors)
    if not isinstance(s, six.string_types):
        try:
            if six.PY3:
                return six.text_type(s).encode(encoding)
            else:
                return bytes(s)
        except UnicodeEncodeError:
            if isinstance(s, Exception):
                # An Exception subclass containing non-ASCII data that doesn't
                # know how to print itself properly. We shouldn't raise a
                # further exception.
                return b" ".join(
                    force_bytes(arg, encoding, strings_only, errors)
                    for arg in s
                )
            return six.text_type(s).encode(encoding, errors)
    else:
        return s.encode(encoding, errors)


def force_text(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Similar to smart_text, except that lazy instances are resolved to
    strings, rather than kept as lazy objects.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    # Handle the common case first for performance reasons.
    if issubclass(type(s), six.text_type):
        return s
    if strings_only and is_protected_type(s):
        return s
    try:
        if not issubclass(type(s), six.string_types):
            if six.PY3:
                if isinstance(s, bytes):
                    s = six.text_type(s, encoding, errors)
                else:
                    s = six.text_type(s)
            elif hasattr(s, "__unicode__"):
                s = six.text_type(s)
            else:
                s = six.text_type(bytes(s), encoding, errors)
        else:
            # Note: We use .decode() here, instead of six.text_type(s, encoding,
            # errors), so that if s is a SafeBytes, it ends up being a
            # SafeText at the end.
            s = s.decode(encoding, errors)
    except UnicodeDecodeError as e:
        if not isinstance(s, Exception):
            raise BTEUnicodeDecodeError(s, *e.args)
        else:
            # If we get to here, the caller has passed in an Exception
            # subclass populated with non-ASCII bytestring data without a
            # working unicode method. Try to handle this without raising a
            # further exception by individually forcing the exception args
            # to unicode.
            s = " ".join(
                force_text(arg, encoding, strings_only, errors) for arg in s
            )
    return s


def smart_text(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Returns a text object representing 's' -- unicode on Python 2 and str on
    Python 3. Treats bytestrings using the 'encoding' codec.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    if isinstance(s, Promise):
        # The input is the result of a gettext_lazy() call.
        return s
    return force_text(s, encoding, strings_only, errors)


class Promise(object):
    """
    This is just a base class for the proxy class created in
    the closure of the lazy function. It can be used to recognize
    promises in code.
    """

    pass


_PROTECTED_TYPES = six.integer_types + (
    type(None),
    float,
    Decimal,
    datetime.datetime,
    datetime.date,
    datetime.time,
)


def is_protected_type(obj):
    """Determine if the object instance is of a protected type.

    Objects of protected types are preserved as-is when passed to
    force_text(strings_only=True).
    """
    return isinstance(obj, _PROTECTED_TYPES)
