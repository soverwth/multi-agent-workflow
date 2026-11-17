import tempfile
import unittest
from pathlib import Path

from b03_implementation.campus_db import CampusDB
from b03_implementation.errors import (
    DuplicateAccount,
    DuplicateClaim,
    Forbidden,
    InvalidField,
    NotFound,
    RequiredField,
)


class TestCampusDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = CampusDB(Path(self.tmp.name) / "campus.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_account_case_insensitive(self):
        self.db.register_user("Alice", "pw1", "甲")
        with self.assertRaises(DuplicateAccount):
            self.db.register_user("alice", "pw2", "乙")

    def test_account_charset_and_length(self):
        with self.assertRaises(InvalidField):
            self.db.register_user("ab!", "pw", "甲")
        with self.assertRaises(InvalidField):
            self.db.register_user("ab", "pw", "甲")

    def test_password_hash_not_in_profile(self):
        user = self.db.register_user("bob", "pw", "鲍勃")
        self.assertNotIn("password_hash", user)
        self.assertIsNotNone(self.db.verify_password("bob", "pw"))
        self.assertIsNone(self.db.verify_password("bob", "wrong"))

    def test_lost_at_required_and_iso8601(self):
        user = self.db.register_user("carol", "pw", " Carol ")
        with self.assertRaises(RequiredField):
            self.db.publish_lost(
                publisher_id=user["id"],
                name="钥匙",
                description="一串",
                location="图书馆",
                lost_at="",
            )
        with self.assertRaises(InvalidField):
            self.db.publish_lost(
                publisher_id=user["id"],
                name="钥匙",
                description="一串",
                location="图书馆",
                lost_at="2026-11-16",
            )
        item = self.db.publish_lost(
            publisher_id=user["id"],
            name="钥匙",
            description="一串",
            location="图书馆",
            lost_at="2026-11-16T10:30:00+08:00",
        )
        self.assertIsNotNone(item)

    def test_lost_view_has_no_publisher_id(self):
        user = self.db.register_user("dave", "pw", "戴夫")
        item = self.db.publish_lost(
            publisher_id=user["id"],
            name="水杯",
            description="蓝色",
            location="食堂",
            lost_at="2026-11-16T10:30:00+08:00",
        )
        view = self.db.get_lost(item["id"])
        self.assertNotIn("publisher_id", view)
        self.assertEqual(self.db.search_lost(keyword="水杯")[0]["id"], item["id"])

    def test_self_claim_forbidden(self):
        user = self.db.register_user("eve", "pw", "夏娃")
        item = self.db.publish_lost(
            publisher_id=user["id"],
            name="书",
            description="教材",
            location="教室",
            lost_at="2026-11-16T10:30:00+08:00",
        )
        with self.assertRaises(Forbidden):
            self.db.create_claim(
                lost_item_id=item["id"], applicant_id=user["id"], statement="我的"
            )

    def test_duplicate_claim(self):
        owner = self.db.register_user("frank", "pw", "弗兰克")
        applicant = self.db.register_user("grace", "pw", "格蕾丝")
        item = self.db.publish_lost(
            publisher_id=owner["id"],
            name="耳机",
            description="黑色",
            location="宿舍",
            lost_at="2026-11-16T10:30:00+08:00",
        )
        self.db.create_claim(
            lost_item_id=item["id"], applicant_id=applicant["id"], statement="我捡到了"
        )
        with self.assertRaises(DuplicateClaim):
            self.db.create_claim(
                lost_item_id=item["id"], applicant_id=applicant["id"], statement="再次申请"
            )

    def test_claim_not_found_and_my_claims(self):
        owner = self.db.register_user("henry", "pw", "亨利")
        applicant = self.db.register_user("ivy", "pw", "艾维")
        item = self.db.publish_lost(
            publisher_id=owner["id"],
            name="电脑",
            description="笔记本",
            location="自习室",
            lost_at="2026-11-16T10:30:00+08:00",
        )
        with self.assertRaises(NotFound):
            self.db.create_claim(
                lost_item_id="missing", applicant_id=applicant["id"], statement="捡到"
            )
        self.db.create_claim(
            lost_item_id=item["id"], applicant_id=applicant["id"], statement="特征一致"
        )
        self.assertEqual(len(self.db.list_my_claims(applicant["id"])), 1)

    def test_load_test_data(self):
        ids = self.db.load_test_data()
        self.assertEqual(len(ids["users"]), 2)
        self.assertEqual(len(ids["lost_items"]), 1)
        self.assertEqual(len(ids["claims"]), 1)
