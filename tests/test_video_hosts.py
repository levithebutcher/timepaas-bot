"""
Unit tests for video host resolvers: Streamtape, Doodstream, Mixdrop, Streamwish.
"""

import unittest
import re
from bot.extractors.video_hosts import (
    is_matching_host,
    evaluate_streamtape_js,
    sanitize_streamtape_url,
    STREAMTAPE_DOMAINS,
    DOOD_DOMAINS,
    MIXDROP_DOMAINS,
    STREAMWISH_DOMAINS,
    FILELIONS_DOMAINS
)


class TestVideoHosts(unittest.TestCase):

    def test_domain_matching(self):
        # Streamtape
        self.assertTrue(is_matching_host("streamtape.com", STREAMTAPE_DOMAINS))
        self.assertTrue(is_matching_host("strtape.tech", STREAMTAPE_DOMAINS))
        self.assertTrue(is_matching_host("subdomain.streamtape.to", STREAMTAPE_DOMAINS))

        # Doodstream
        self.assertTrue(is_matching_host("dood.to", DOOD_DOMAINS))
        self.assertTrue(is_matching_host("doodstream.com", DOOD_DOMAINS))
        self.assertTrue(is_matching_host("ds2play.com", DOOD_DOMAINS))

        # Mixdrop
        self.assertTrue(is_matching_host("mixdrop.co", MIXDROP_DOMAINS))
        self.assertTrue(is_matching_host("mixdrop.sx", MIXDROP_DOMAINS))

        # Streamwish & Filelions
        self.assertTrue(is_matching_host("streamwish.to", STREAMWISH_DOMAINS))
        self.assertTrue(is_matching_host("filelions.com", FILELIONS_DOMAINS))

        # Non-matching
        self.assertFalse(is_matching_host("youtube.com", STREAMTAPE_DOMAINS))
        self.assertFalse(is_matching_host("google.com", DOOD_DOMAINS))

    def test_streamtape_regex_token_extraction(self):
        # Mock HTML with robotlink assignment
        mock_html = """
        <html>
        <head><title>Video</title></head>
        <body>
        <script>
        document.getElementById('robotlink').innerHTML = '//streamtape.com/get_video?id=abc12345&token=sample_token_xyz';
        </script>
        </body>
        </html>
        """
        match = re.search(
            r"document\.getElementById\(['\"](?:robotlink|ideoolink|norobotlink)['\"]\)[\s\.]*innerHTML\s*=\s*['\"]([^'\"]+)['\"]",
            mock_html
        )
        self.assertIsNotNone(match)
        url = match.group(1)
        if url.startswith("//"):
            url = "https:" + url
        self.assertEqual(url, "https://streamtape.com/get_video?id=abc12345&token=sample_token_xyz")

    def test_streamtape_concatenated_string_extraction(self):
        # Mock HTML with multi-part concatenation
        mock_html = """
        <script>
        document.getElementById('ideoolink').innerHTML = '//streamtape.com/get_video?' + 'id=testfile' + '&token=tok_987';
        </script>
        """
        concat_match = re.search(
            r"getElementById\(['\"](?:robotlink|ideoolink)['\"]\)[\s\.]*inner(?:HTML)?\s*=\s*(.+?);",
            mock_html
        )
        self.assertIsNotNone(concat_match)
        raw_expr = concat_match.group(1)
        tokens = re.findall(r"['\"]([^'\"]+)['\"]", raw_expr)
        combined = "".join(tokens)
        if combined.startswith("//"):
            combined = "https:" + combined
        self.assertEqual(combined, "https://streamtape.com/get_video?id=testfile&token=tok_987")


    def test_evaluate_streamtape_js_function(self):
        expr = "'//streamtape.com/get_video?id=9Bl9qkyZrMCarxy&token=' + ('junkprefix_token123').substring(11)"
        result = evaluate_streamtape_js(expr)
        self.assertEqual(result, "//streamtape.com/get_video?id=9Bl9qkyZrMCarxy&token=token123")


    def test_sanitize_streamtape_url(self):
        # Test neutralizing decoy domains with typos
        decoy_1 = "https://stdreamtape.com/get_video?id=123&token=abc"
        self.assertEqual(sanitize_streamtape_url(decoy_1), "https://streamtape.com/get_video?id=123&token=abc")

        decoy_2 = "https://streamtadpe.com/get_video?id=456&token=def"
        self.assertEqual(sanitize_streamtape_url(decoy_2), "https://streamtape.com/get_video?id=456&token=def")

        # Test fixing duplicate domain prefix
        dup = "https://streamtape.com/streamtape.com/get_video?id=789"
        self.assertEqual(sanitize_streamtape_url(dup), "https://streamtape.com/get_video?id=789")


if __name__ == "__main__":
    unittest.main()
