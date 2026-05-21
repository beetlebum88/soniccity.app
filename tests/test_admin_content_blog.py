import tempfile
import unittest
import re
from pathlib import Path

import app as city_app


class AdminContentBlogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_pages = city_app.ADMIN_PAGES_PATH
        self.old_blog = city_app.BLOG_POSTS_PATH
        self.old_upload = city_app.BLOG_UPLOAD_DIR
        self.old_cms_store = city_app.ADMIN_CMS_STORE_PATH
        self.old_admin_initial_password = city_app.ADMIN_INITIAL_PASSWORD
        city_app.ADMIN_PAGES_PATH = root / "admin" / "pages.json"
        city_app.BLOG_POSTS_PATH = root / "blog" / "posts.json"
        city_app.BLOG_UPLOAD_DIR = root / "uploads"
        city_app.ADMIN_CMS_STORE_PATH = root / "admin" / "cms.json"
        city_app.ADMIN_INITIAL_PASSWORD = "Qawsedrf12@"
        self.client = city_app.app.test_client()

    def csrf(self, path="/admin/login"):
        resp = self.client.get(path)
        html = resp.data.decode("utf-8", "ignore")
        match = re.search(r'name="csrf-token" content="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)

    def tearDown(self):
        city_app.ADMIN_PAGES_PATH = self.old_pages
        city_app.BLOG_POSTS_PATH = self.old_blog
        city_app.BLOG_UPLOAD_DIR = self.old_upload
        city_app.ADMIN_CMS_STORE_PATH = self.old_cms_store
        city_app.ADMIN_INITIAL_PASSWORD = self.old_admin_initial_password
        self.tmp.cleanup()

    def login(self):
        token = self.csrf("/admin/login")
        return self.client.post(
            "/admin/login",
            data={"email": city_app.ADMIN_EMAIL, "password": "Qawsedrf12@", "csrf_token": token},
            follow_redirects=False,
        )

    def test_admin_requires_login_and_accepts_session_login(self):
        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login", resp.headers["Location"])

        resp = self.login()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/admin")

        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Blog articles", resp.data)
        self.assertIn(b"Pages / SEO", resp.data)

    def test_admin_pages_and_localized_admin_urls_do_not_404(self):
        self.login()
        resp = self.client.get("/admin/pages")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"All pages", resp.data)

        resp = self.client.get("/ua/admin/pages?page=home")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/admin/pages?page=home")

        resp = self.client.get("/admin/pages")
        html = resp.data.decode("utf-8", "ignore")
        self.assertIn('/admin/pages', html)
        self.assertNotIn('/ua/admin/pages', html)

    def test_admin_page_content_is_saved_and_rendered_safely(self):
        self.login()
        resp = self.client.post(
            "/admin/pages",
            data={
                "csrf_token": self.csrf("/admin/pages"),
                "lang": "en",
                "page_type": "home",
                "seo_text_markdown": "## Better guide\n\n<script>alert(1)</script>Safe copy.",
                "faq_question": ["Can I listen free?"],
                "faq_answer": ["Yes, start the free Audio Guide and pick a city."],
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        content = city_app.load_admin_page_content("home", "en")
        self.assertIn("Better guide", content["seoTextHtml"])
        self.assertNotIn("<script>", content["seoTextHtml"])
        self.assertEqual(content["faq"][0]["question"], "Can I listen free?")
        public = self.client.get("/")
        self.assertIn(b"Better guide", public.data)
        self.assertIn(b"Can I listen free?", public.data)

    def test_admin_page_html_editor_is_saved_and_sanitized(self):
        self.login()
        resp = self.client.post(
            "/admin/pages",
            data={
                "csrf_token": self.csrf("/admin/pages"),
                "lang": "en",
                "page_type": "home",
                "seo_editor_mode": "html",
                "seo_text_markdown": "",
                "seo_text_html_raw": '<h2>Free Audio Guide</h2><p>Listen before you go.</p><script>alert(1)</script><a href="javascript:alert(1)">bad</a>',
                "faq_question": [],
                "faq_answer": [],
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        content = city_app.load_admin_page_content("home", "en")
        self.assertEqual(content["seoEditorMode"], "html")
        self.assertIn("<h2>Free Audio Guide</h2>", content["seoTextHtml"])
        self.assertIn("Listen before you go.", content["seoTextHtml"])
        self.assertNotIn("<script>", content["seoTextHtml"])
        self.assertNotIn("javascript:", content["seoTextHtml"])

    def test_blog_drafts_are_hidden_and_published_posts_are_visible(self):
        self.login()
        draft = self.client.post(
            "/admin/blog/new",
            data={
                "csrf_token": self.csrf("/admin/blog/new"),
                "title": "Hidden draft",
                "slug": "hidden-draft",
                "lang": "en",
                "status": "draft",
                "category": "Travel",
                "excerpt": "Draft excerpt",
                "body_markdown": "Draft body",
            },
        )
        self.assertEqual(draft.status_code, 302)
        self.assertNotIn(b"Hidden draft", self.client.get("/blog").data)

        published = self.client.post(
            "/admin/blog/new",
            data={
                "csrf_token": self.csrf("/admin/blog/new"),
                "title": "Valencia audio tips",
                "slug": "valencia-audio-tips",
                "lang": "en",
                "status": "published",
                "category": "Cities",
                "tags": "Valencia, Audio Guide",
                "excerpt": "Listen before your trip.",
                "body_markdown": "## Listen free\n\nUseful **Audio Guide** tips.",
                "meta_title": "Valencia Audio Guide Blog",
                "meta_description": "Free Valencia Audio Guide blog tips.",
            },
        )
        self.assertEqual(published.status_code, 302)
        self.assertIn(b"Valencia audio tips", self.client.get("/blog").data)
        self.assertIn(b"Listen free", self.client.get("/blog/valencia-audio-tips").data)


if __name__ == "__main__":
    unittest.main()
