#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

import create_user as cu


class ValidationTests(unittest.TestCase):
    def test_username_too_long(self) -> None:
        with self.assertRaises(cu.UserScriptError):
            cu.validate_username("a" * 21)

    def test_password_semicolon_forbidden(self) -> None:
        with self.assertRaises(cu.UserScriptError):
            cu.validate_password("GoodPass1;bad")

    def test_password_policy(self) -> None:
        self.assertEqual(cu.validate_password("Pe1fCLpx2hJc!"), "Pe1fCLpx2hJc!")

    def test_ticket_username_length(self) -> None:
        self.assertEqual(cu.validate_username("adNcins"), "adNcins")


class AttributeTests(unittest.TestCase):
    def test_create_attributes_include_keycloak_source_fields(self) -> None:
        attrs = cu.attributes_for_create("adNcinsSfa")
        for key in cu.REQUIRED_AD_ATTRIBUTES:
            self.assertIn(key, attrs)
            self.assertTrue(attrs[key])
        self.assertEqual(attrs["sAMAccountName"], "adNcinsSfa")
        self.assertEqual(attrs["alfaMiisEqNumber"], "9999")
        self.assertEqual(attrs["alfaMiisEqMnemonic"], "MAA6")
        self.assertEqual(attrs["alfaMiisEqProfile"], "1111")

    def test_missing_claims_detects_current_adncins_token(self) -> None:
        current = {
            "sAMAccountName": "adNcins",
            "preferred_username": "adncins",
            "email": "msyakovlev@alfabank.ru",
            "groups": ["EOS_Manager_UL"],
        }
        missing = cu.missing_claims(current)
        for claim in (
            "given_name",
            "family_name",
            "middle_name",
            "displayName",
            "title",
            "department",
            "alfaMiisEqNumber",
            "alfaMiisEqMnemonic",
            "alfaMiisEqProfile",
        ):
            self.assertIn(claim, missing)

    def test_missing_claims_ok_for_template_token(self) -> None:
        template = {
            "sAMAccountName": "u_m1n2y",
            "preferred_username": "u_m1n2y",
            "email": "lekanov@alfabank.ru",
            "given_name": "Михаил",
            "family_name": "Леканов",
            "middle_name": "Васильевич",
            "name": "Михаил Леканов",
            "displayName": "Леканов Михаил Васильевич",
            "title": "Должность",
            "department": "Развития оффлайн каналов",
            "alfaMiisEqNumber": "9999",
            "alfaMiisEqMnemonic": "MAA6",
            "alfaMiisEqProfile": "1111",
        }
        self.assertEqual(cu.missing_claims(template), [])


class CsvTests(unittest.TestCase):
    def test_write_users_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Users.csv"
            cu.write_users_csv(path, [cu.csv_row("adNcinsSfa", "Pe1fCLpx2hJc!")])
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("alfaMiisEqNumber", text)
            self.assertIn("adNcinsSfa", text)
            self.assertIn("Pe1fCLpx2hJc!", text)

    def test_csv_batch_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Users.csv"
            rows = [cu.csv_row(f"user{i:02d}", "Pe1fCLpx2hJc!") for i in range(31)]
            with self.assertRaises(cu.UserScriptError):
                cu.write_users_csv(path, rows)


class JwtTests(unittest.TestCase):
    def test_decode_jwt_payload(self) -> None:
        import base64

        payload = base64.urlsafe_b64encode(
            json.dumps({"preferred_username": "adNcins"}).encode("utf-8")
        ).decode("ascii").rstrip("=")
        token = f"aaa.{payload}.bbb"
        self.assertEqual(cu.decode_jwt_payload(token)["preferred_username"], "adNcins")


if __name__ == "__main__":
    unittest.main()
