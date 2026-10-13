"""A drug or brand name in the question must appear in every search result.

Client test 2026-10-13: "tibolone" (5 competitor articles) came back padded
with calamine and diltiazem pages that never name it. See
core/knowledge.py:_specific_terms for the rule and the measurements.
"""

from unittest import mock, skipUnless

from django.test import SimpleTestCase

from core import knowledge

try:
    import wordfreq  # noqa: F401
    HAS_WORDFREQ = True
except ImportError:  # the CI requirements leave it out on purpose
    HAS_WORDFREQ = False


def _corpus():
    # 100 items: "tibolone" in 2 (2%, rare), "consigliano" in 2 (rare here,
    # but ordinary Italian), "menopausa" in all of them.
    items = []
    for i in range(100):
        text = "menopausa e sintomi"
        if i < 2:
            text += " tibolone"
        elif i < 4:
            text += " consigliano"
        items.append({"hay": text})
    return items


@skipUnless(HAS_WORDFREQ, "wordfreq non installato")
class SpecificTermsTest(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(knowledge, "_load_index", return_value=_corpus())
        p.start()
        self.addCleanup(p.stop)

    def test_rare_drug_name_is_specific(self):
        self.assertEqual(knowledge._specific_terms("tibolone"), ["tibolone"])

    def test_rare_ordinary_word_is_not(self):
        self.assertEqual(knowledge._specific_terms("cosa consigliano"), [])

    def test_common_topic_is_not(self):
        self.assertEqual(knowledge._specific_terms("menopausa"), [])

    def test_word_found_nowhere_is_not(self):
        # A typo must not empty the search.
        self.assertEqual(knowledge._specific_terms("tiboxyz"), [])
