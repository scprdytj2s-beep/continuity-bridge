"""Licentiecontrole in de app (ale_merger_gui.py) — ook tegen de JS-serverkant.

    python3 -m unittest discover -s tests

De kruistests met lib/security.js en api/activate.js hebben `node` nodig.
"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ale_merger_gui as app  # noqa: E402

HAS_NODE = shutil.which("node") is not None
MACHINE = "TEST-MACHINE-UUID"

# RFC 8032 §7.1, test 1-3: (publieke sleutel, bericht, handtekening)
RFC8032 = [
    ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


def node(script, seed=None, **env):
    """Draai JS met lib/security.js als `sec`; returns stdout (gestript)."""
    full_env = {**os.environ, **env}
    if seed:
        full_env["LIC_SIGNING_KEY"] = base64.b64encode(seed).decode()
    return subprocess.run(
        ["node", "-e", f"const sec = require('./lib/security'); {script}"],
        cwd=ROOT, env=full_env, capture_output=True, text=True, check=True,
    ).stdout.strip()


def legacy_serial(name, expiry):
    """Zoals de oude, publieke _serial_generate — wat een keygen maakt."""
    import hashlib, hmac, struct
    payload = struct.pack(">H", (expiry - date(2024, 1, 1)).days) + \
        name.encode()[:8].ljust(8, b"\0")
    sig = hmac.new(b"CB2026-ContBridge-HMAC-S3cr3t-K3y", payload, hashlib.sha256).digest()[:5]
    b32 = base64.b32encode(payload + sig).decode()
    return "CB-" + "-".join(b32[i:i + 4] for i in range(0, 24, 4))


class Ed25519Test(unittest.TestCase):
    def test_rfc8032_vectors(self):
        for pub, msg, sig in RFC8032:
            pub, msg, sig = bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig)
            self.assertTrue(app._ed25519_verify(pub, msg, sig))
            self.assertFalse(app._ed25519_verify(pub, msg + b"x", sig))
            bad = bytearray(sig); bad[10] ^= 1
            self.assertFalse(app._ed25519_verify(pub, msg, bytes(bad)))

    def test_rejects_malformed(self):
        pub, msg, sig = (bytes.fromhex(x) for x in RFC8032[1])
        self.assertFalse(app._ed25519_verify(pub[:31], msg, sig))
        self.assertFalse(app._ed25519_verify(pub, msg, sig[:63]))
        # S ≥ L (niet-canonieke handtekening) → weigeren
        s = int.from_bytes(sig[32:], "little") + app._ED_L
        self.assertFalse(app._ed25519_verify(pub, msg, sig[:32] + s.to_bytes(32, "little")))

    @unittest.skipUnless(HAS_NODE, "node ontbreekt")
    def test_cross_node_random(self):
        seed = secrets.token_bytes(32)
        msgs = [secrets.token_bytes(n) for n in (0, 1, 31, 64, 200, 1000) for _ in range(5)]
        out = node(
            "const s = sec.signingSeed();"
            "const k = require('crypto').createPrivateKey({key: Buffer.concat(["
            "Buffer.from('302e020100300506032b657004220420','hex'), s]), format:'der', type:'pkcs8'});"
            f"const msgs = {json.dumps([m.hex() for m in msgs])};"
            "console.log(JSON.stringify({pub: sec.signingPublicKeyHex(s), sigs: msgs.map(m =>"
            " require('crypto').sign(null, Buffer.from(m,'hex'), k).toString('hex'))}));",
            seed=seed)
        data = json.loads(out)
        pub = bytes.fromhex(data["pub"])
        for m, sig in zip(msgs, data["sigs"]):
            self.assertTrue(app._ed25519_verify(pub, m, bytes.fromhex(sig)))
            self.assertFalse(app._ed25519_verify(pub, m + b"\0", bytes.fromhex(sig)))


class LicenseTestBase(unittest.TestCase):
    def setUp(self):
        self.seed = secrets.token_bytes(32)
        self.tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(app, "_machine_uuid", return_value=MACHINE),
            mock.patch.object(app, "_LIC_FILE", Path(self.tmp.name) / "license"),
            mock.patch.object(app, "_revoked_serials", set()),
        ]
        if HAS_NODE:
            patches.append(mock.patch.object(app, "_LIC_PUBKEY", bytes.fromhex(
                node("console.log(sec.signingPublicKeyHex(sec.signingSeed()))", seed=self.seed))))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def issue(self, name, expiry=None):
        exp = f"new Date('{expiry.isoformat()}T00:00:00Z')" if expiry else "undefined"
        return node(f"console.log(sec.issueSerial({json.dumps(name)}, sec.signingSeed(), {exp}))",
                    seed=self.seed)

    def token(self, serial, mid=MACHINE):
        return subprocess.run(
            ["node", "tools/license-admin.js", "token", serial, mid], cwd=ROOT,
            env={**os.environ, "LIC_SIGNING_KEY": base64.b64encode(self.seed).decode()},
            capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(HAS_NODE, "node ontbreekt")
class LicenseCheckTest(LicenseTestBase):
    def test_serial_decode_reads_js_serial(self):
        serial = self.issue("Pieter Pietersen", date.today() + timedelta(days=100))
        ok, expiry, name, _ = app._serial_decode(serial)
        self.assertTrue(ok)
        self.assertEqual(name, "Pieter P")
        self.assertEqual(expiry, date.today() + timedelta(days=100))

    def test_valid_token(self):
        serial = self.issue("Anna")
        ok, expiry, name, _, needs_online = app._license_check(
            {"serial": serial, "token": self.token(serial)})
        self.assertTrue(ok)
        self.assertFalse(needs_online)
        self.assertEqual(name, "Anna")
        self.assertGreater(expiry, date.today())

    def test_token_from_other_key_rejected(self):
        serial = self.issue("Anna")
        claims = {"v": 1, "serial": serial, "name": "Anna", "exp": "2099-01-01", "mid": MACHINE}
        forged = node(f"console.log(sec.signActivationToken({json.dumps(claims)}, sec.signingSeed()))",
                      seed=secrets.token_bytes(32))
        self.assertFalse(app._license_check({"serial": serial, "token": forged})[0])

    def test_token_tampered_claims_rejected(self):
        serial = self.issue("Anna")
        prefix, body, sig = self.token(serial).split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=="))
        claims["exp"] = "2099-12-31"
        body2 = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        self.assertFalse(app._license_check(
            {"serial": serial, "token": f"{prefix}.{body2}.{sig}"})[0])

    def test_token_for_other_serial_or_machine_rejected(self):
        a, b = self.issue("Anna"), self.issue("Bert")
        self.assertFalse(app._license_check({"serial": b, "token": self.token(a)})[0])
        self.assertFalse(app._license_check(
            {"serial": a, "token": self.token(a, mid="ANDERE-MAC")})[0])

    def test_revoked(self):
        serial = self.issue("Anna")
        app._revoked_serials.add(app._serial_core(serial))
        ok, _, _, msg, _ = app._license_check({"serial": serial, "token": self.token(serial)})
        self.assertFalse(ok)
        self.assertIn("ingetrokken", msg)

    def test_expired_token(self):
        serial = self.issue("Anna", date.today() + timedelta(days=1))
        tok = self.token(serial)
        with mock.patch.object(app, "_date", mock.Mock(
                wraps=date, today=lambda: date.today() + timedelta(days=2),
                fromisoformat=date.fromisoformat)):
            self.assertFalse(app._license_check({"serial": serial, "token": tok})[0])

    def test_pending_grace_period(self):
        serial = self.issue("Anna")
        since = (date.today() - timedelta(days=3)).isoformat()
        ok, _, _, msg, needs_online = app._license_check(
            {"serial": serial, "machine_id": MACHINE, "pending_since": since})
        self.assertTrue(ok)
        self.assertTrue(needs_online)
        self.assertIn(str(app._LIC_GRACE_DAYS - 3), msg)

        over = (date.today() - timedelta(days=app._LIC_GRACE_DAYS)).isoformat()
        self.assertFalse(app._license_check(
            {"serial": serial, "machine_id": MACHINE, "pending_since": over})[0])
        # Licentiebestand van een andere Mac gekopieerd
        self.assertFalse(app._license_check(
            {"serial": serial, "machine_id": "ANDERE-MAC", "pending_since": since})[0])

    def test_save_and_load(self):
        serial = self.issue("Anna")
        app._license_save(serial, token=self.token(serial))
        lic = app._license_load()
        self.assertEqual(lic["machine_id"], MACHINE)
        self.assertTrue(app._license_check(lic)[0])
        self.assertEqual(oct(app._LIC_FILE.stat().st_mode & 0o777), "0o600")
        app._license_save(serial)
        self.assertEqual(app._license_load()["pending_since"], date.today().isoformat())


@unittest.skipUnless(HAS_NODE, "node ontbreekt")
class ActivateEndToEndTest(LicenseTestBase):
    """App-code (_activate_online) tegen de echte api/activate.js-handler."""

    def setUp(self):
        super().setUp()
        self.legacy_ok = legacy_serial("Klant", date.today() + timedelta(days=200))
        self.server = subprocess.Popen(
            ["node", "tests/serve-api.js"], cwd=ROOT, stdout=subprocess.PIPE, text=True,
            env={**os.environ, "LIC_SIGNING_KEY": base64.b64encode(self.seed).decode(),
                 "LEGACY_SERIALS": self.legacy_ok, "GITHUB_TOKEN": ""})
        self.addCleanup(self.server.stdout.close)
        self.addCleanup(self.server.wait)
        self.addCleanup(self.server.terminate)
        port = self.server.stdout.readline().strip()
        p = mock.patch.object(app, "_LIC_API", f"http://127.0.0.1:{port}/api")
        p.start()
        self.addCleanup(p.stop)

    def test_real_serial_gets_valid_token(self):
        serial = self.issue("Anna")
        result, token = app._activate_online(serial)
        self.assertEqual(result, "ok")
        app._license_save(serial, token=token)
        self.assertTrue(app._license_check(app._license_load())[0])

    def test_keygen_serial_rejected(self):
        forged = legacy_serial("Hacker", date.today() + timedelta(days=300))
        self.assertTrue(app._serial_decode(forged)[0])   # formaat klopt wél
        self.assertEqual(app._activate_online(forged), ("rejected", "niet_erkend"))

    def test_grandfathered_legacy_serial_gets_token(self):
        result, token = app._activate_online(self.legacy_ok)
        self.assertEqual(result, "ok")
        self.assertTrue(app._license_check({"serial": self.legacy_ok, "token": token})[0])

    def test_garbage_and_expired(self):
        serial = self.issue("Anna")
        bad = serial[:-1] + ("A" if serial[-1] != "A" else "B")
        self.assertEqual(app._activate_online(bad), ("rejected", "ongeldig"))
        old = self.issue("Oud", date(2025, 1, 1))
        self.assertEqual(app._activate_online(old), ("rejected", "verlopen"))

    def test_deactivate(self):
        serial = self.issue("Anna")
        result, token = app._activate_online(serial)
        self.assertEqual(result, "ok")
        self.assertTrue(app._deactivate_online(token))
        self.assertTrue(app._deactivate_online("onzin"))   # niets vrij te geven
        with mock.patch.object(app, "_LIC_API", "http://127.0.0.1:9/api"):
            self.assertFalse(app._deactivate_online(token))

    def test_server_unreachable_is_offline(self):
        with mock.patch.object(app, "_LIC_API", "http://127.0.0.1:9/api"):
            self.assertEqual(app._activate_online(self.issue("Anna")), ("offline", None))


@unittest.skipUnless(HAS_NODE, "node ontbreekt")
class ServerConfigTest(LicenseTestBase):
    def test_missing_signing_key_is_offline_not_rejected(self):
        server = subprocess.Popen(
            ["node", "tests/serve-api.js"], cwd=ROOT, stdout=subprocess.PIPE, text=True,
            env={k: v for k, v in os.environ.items() if k != "LIC_SIGNING_KEY"})
        self.addCleanup(server.stdout.close)
        self.addCleanup(server.wait)
        self.addCleanup(server.terminate)
        port = server.stdout.readline().strip()
        with mock.patch.object(app, "_LIC_API", f"http://127.0.0.1:{port}/api"):
            self.assertEqual(app._activate_online(self.issue("Anna")), ("offline", None))


if __name__ == "__main__":
    unittest.main()
