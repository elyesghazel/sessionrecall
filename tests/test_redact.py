import io

import pytest

from sessionrecall.redact import MASK, RedactingWriter, redact

# Built from pieces so the repo never contains anything a secret scanner would flag.
FAKE_TOKENS = [
    "sk-" + "ant-" + "a1" * 15,
    "sk-" + "proj-" + "Ab3" * 8,
    "gh" + "p_" + "A1b2" * 9,
    "github" + "_pat_" + "x9" * 20,
    "gl" + "pat-" + "z" * 24,
    "xo" + "xb-" + "1234567890-abc",
    "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "AI" + "za" + "B" * 35,
    "ya" + "29." + "c" * 30,
    "sh" + "pat_" + "a" * 32,
    "wh" + "sec_" + "w" * 24,
    "sk" + "_live_" + "s" * 24,
    "rk" + "_live_" + "r" * 24,
    "ey" + "J" + "h" * 12 + ".ey" + "J" + "p" * 12 + "." + "s" * 12,
]


@pytest.mark.parametrize("token", FAKE_TOKENS)
def test_known_token_formats(token):
    out = redact(f"use {token} for this")
    assert token not in out
    assert out == f"use {MASK} for this"


@pytest.mark.parametrize(
    "text, kept",
    [
        ("password=correcthorse42", "password="),
        ('api_key: "abcd1234efgh"', 'api_key: "'),
        ("DB_PASSWORD = s3cr3tvalue!", "DB_PASSWORD = "),
        ("client_secret=zzzzzzzzzz", "client_secret="),
    ],
)
def test_keyword_values(text, kept):
    out = redact(text)
    assert out.startswith(kept + MASK)


@pytest.mark.parametrize("text", ["token=$GITHUB_TOKEN", "password=<your-password>", "secret={{ vault.secret }}"])
def test_placeholders_stay(text):
    assert redact(text) == text


def test_short_values_stay():
    assert redact("pw=abc") == "pw=abc"


def test_bearer_header():
    out = redact("Authorization: Bearer abcdefghijklmnop1234")
    assert out == f"Authorization: Bearer {MASK}"


def test_url_credentials():
    out = redact("postgres://app:hunter2hunter2@db.internal:5432/shop")
    assert out == f"postgres://app:{MASK}@db.internal:5432/shop"


def test_private_key_block():
    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3Nza\n-----END OPENSSH PRIVATE KEY-----"
    assert redact(f"key:\n{pem}\nend") == f"key:\n{MASK}\nend"


def test_truncated_private_key():
    assert redact("-----BEGIN RSA PRIVATE KEY-----\nMIIEow") == MASK


def test_plain_text_untouched():
    text = "The checkout test fails one run in five because the query has no ORDER BY."
    assert redact(text) == text


def test_redacting_writer():
    buf = io.StringIO()
    w = RedactingWriter(buf)
    print("password=correcthorse42", file=w)
    assert buf.getvalue() == f"password={MASK}\n"
