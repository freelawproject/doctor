# -*- coding: utf-8 -*-
from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import unittest
from unittest import TestCase


class SomeTest(TestCase):
    """Testing to come soon."""

    def test_something(self):
        """A testing template"""

        matches = True
        expected_matches = True
        self.assertEqual(matches, expected_matches)


if __name__ == "__main__":
    unittest.main()
