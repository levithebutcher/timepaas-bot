"""
Unit tests for video host resolvers: Streamtape, Doodstream, Mixdrop, Streamwish.
"""

import unittest
import re
from bot.extractors.video_hosts import (
    is_matching_host,
    is_streamtape_host,
    is_luluvid_host,
    unpack_dean_edwards,
    evaluate_streamtape_js,
    sanitize_streamtape_url,
    STREAMTAPE_DOMAINS,
    DOOD_DOMAINS,
    MIXDROP_DOMAINS,
    STREAMWISH_DOMAINS,
    FILELIONS_DOMAINS,
    LULUSTREAM_DOMAINS,
    EPORNER_DOMAINS,
    calc_eporner_hash
)


class TestVideoHosts(unittest.TestCase):

    def test_domain_matching(self):
        # Streamtape & Mirrors
        self.assertTrue(is_matching_host("streamtape.com", STREAMTAPE_DOMAINS))
        self.assertTrue(is_matching_host("strtape.tech", STREAMTAPE_DOMAINS))
        self.assertTrue(is_matching_host("subdomain.streamtape.to", STREAMTAPE_DOMAINS))
        self.assertTrue(is_streamtape_host("tapedstream.com"))
        self.assertTrue(is_streamtape_host("tapedstream.xyz"))
        self.assertTrue(is_streamtape_host("strcloud.link"))
        self.assertTrue(is_streamtape_host("stape.fun"))
        self.assertTrue(is_streamtape_host("watchadsontape.com"))

        # LuluStream & LuluVideo Mirrors
        self.assertTrue(is_matching_host("luluvdo.com", LULUSTREAM_DOMAINS))
        self.assertTrue(is_matching_host("luluvideo.com", LULUSTREAM_DOMAINS))
        self.assertTrue(is_matching_host("lulustream.com", LULUSTREAM_DOMAINS))
        self.assertTrue(is_luluvid_host("luluvdo.com"))
        self.assertTrue(is_luluvid_host("luluvideo.com"))
        self.assertTrue(is_luluvid_host("sub.luluvdo.com"))
        self.assertTrue(is_luluvid_host("luluvd.com"))

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

        # Eporner
        self.assertTrue(is_matching_host("eporner.com", EPORNER_DOMAINS))
        self.assertTrue(is_matching_host("www.eporner.com", EPORNER_DOMAINS))
        self.assertTrue(is_matching_host("sub.eporner.net", EPORNER_DOMAINS))

        # Non-matching
        self.assertFalse(is_matching_host("youtube.com", STREAMTAPE_DOMAINS))
        self.assertFalse(is_matching_host("google.com", DOOD_DOMAINS))
        self.assertFalse(is_streamtape_host("randomsite.xyz"))
        self.assertFalse(is_luluvid_host("randomsite.xyz"))

    def test_eporner_hash_calculation(self):
        sample_hash = "abcdef0123456789abcdef0123456789"
        calculated = calc_eporner_hash(sample_hash)
        self.assertIsInstance(calculated, str)
        self.assertGreater(len(calculated), 10)
        self.assertEqual(calculated, "1bo3u2p9sba151bo3u2p9sba15")

    def test_dean_edwards_unpacker_multiblock(self):
        sample = (
            "eval(function(p,a,c,k,e,d){return p}('0 1=\"2.3\";',4,4,'var|file|video|m3u8'.split('|')))\n"
            "eval(function(p,a,c,k,e,d){return p}('0 1=\"4\";',5,5,'var|title|x|y|SampleTitle'.split('|')))"
        )
        unpacked = unpack_dean_edwards(sample)
        self.assertIn("video.m3u8", unpacked)
        self.assertIn("SampleTitle", unpacked)

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
