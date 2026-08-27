"""The email summary — same facts as the chat block, delivered from an independent CI job.

Everything is pull today: someone has to go and look, and nobody reliably does. This is the push
half, and it deliberately does NOT copy _cmd_notify's swallow-everything behaviour — see the
divergence tests at the bottom, which exist to stop a later "make it consistent" edit.
"""
import pytest

from agent.lib import digest, mail
from tests.test_digest import _PAYLOAD


def _facts(payload=None, **kw):
    return digest.summary_facts(payload or _PAYLOAD, **kw)


# ── rendering ─────────────────────────────────────────────────────────────────────────────────

def test_the_subject_carries_the_headline_so_it_reads_in_a_notification():
    """Most recipients decide whether to open this from the subject line alone."""
    subject, _, _ = mail.summary_mail(_facts())
    assert "12" in subject and "34" in subject


def test_both_parts_are_present_and_the_text_part_is_real():
    """HTML alone breaks in exactly the places an ops mail gets read: a terminal client, a digest,
    a forward into a ticket. The text part is the one that has to survive."""
    _, text, html = mail.summary_mail(_facts())
    assert text.strip(), "the text part is empty"
    assert "<" in html and ">" in html
    assert "<" not in text, "HTML leaked into the plain-text part"


def test_the_text_part_says_what_the_scan_could_not_see():
    """The thesis has to survive into every surface, not just the pretty one."""
    _, text, _ = mail.summary_mail(_facts())
    assert "UNAUDITED" in text and "UPS" in text


def test_a_clean_fleet_renders_zero_not_an_empty_body():
    """An empty body is indistinguishable from a delivery that half-failed."""
    clean = {**_PAYLOAD, "counts": {"fixes": 0, "reposAffected": 0, "reposScanned": 18},
             "actions": [], "catalog": [], "shapes": []}
    subject, text, html = mail.summary_mail(_facts(clean))
    assert "0" in subject
    assert len(text.strip().splitlines()) >= 3
    assert "nothing" in text.lower()


def test_links_appear_only_when_given():
    _, text, _ = mail.summary_mail(_facts())
    assert "http" not in text
    _, text2, _ = mail.summary_mail(_facts(), report_url="https://example.test/r")
    assert "https://example.test/r" in text2


# ── transport ─────────────────────────────────────────────────────────────────────────────────

class _FakeSMTP:
    """Records the envelope. Never opens a socket."""

    def __init__(self):
        self.sent, self.started_tls, self.logged_in = [], False, False

    def starttls(self, *a, **k):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, msg):
        self.sent.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_transport_receives_every_recipient_and_the_configured_sender():
    fake = _FakeSMTP()
    msg = mail.build("subject", "text", "<p>html</p>",
                     sender="drift@example.test", to=["a@example.test", "b@example.test"])
    mail.send("smtps://u:p@smtp.example.test:465", msg, transport=lambda *a, **k: fake)
    assert len(fake.sent) == 1
    out = fake.sent[0]
    assert out["From"] == "drift@example.test"
    assert "a@example.test" in out["To"] and "b@example.test" in out["To"]
    assert out["Subject"] == "subject"


def test_a_plain_smtp_url_upgrades_with_starttls():
    fake = _FakeSMTP()
    msg = mail.build("s", "t", "<p>h</p>", sender="d@e.test", to=["a@e.test"])
    mail.send("smtp://u:p@smtp.example.test:587", msg, transport=lambda *a, **k: fake)
    assert fake.started_tls, "a plain smtp:// URL was used without upgrading to TLS"


def test_a_failed_starttls_raises_rather_than_sending_in_cleartext():
    """The body names client repositories. A silent downgrade is worse than a failed send."""
    class _NoTLS(_FakeSMTP):
        def starttls(self, *a, **k):
            raise OSError("STARTTLS not supported")

    msg = mail.build("s", "t", "<p>h</p>", sender="d@e.test", to=["a@e.test"])
    with pytest.raises(OSError):
        mail.send("smtp://u:p@smtp.example.test:587", msg, transport=lambda *a, **k: _NoTLS())


def test_the_smtp_url_is_never_returned_or_echoed():
    """The password lives in that URL. Nothing here may hand it back to a caller that might log
    it — a test asserts the contract rather than trusting the caller."""
    fake = _FakeSMTP()
    msg = mail.build("s", "t", "<p>h</p>", sender="d@e.test", to=["a@e.test"])
    assert mail.send("smtps://user:hunter2@smtp.example.test:465", msg,
                     transport=lambda *a, **k: fake) is None
