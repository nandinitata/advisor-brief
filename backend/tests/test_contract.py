"""The §7.1 state contract is a Pydantic model, so the hand-off rule is testable
without a model: a draft missing its brief or email must not validate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pydantic import ValidationError

from schemas import DraftContract


def test_complete_draft_validates():
    DraftContract(meeting_brief="Points to cover...", client_email="Hi — quick note...")


def test_empty_brief_fails():
    with pytest.raises(ValidationError):
        DraftContract(meeting_brief="   ", client_email="Hi")


def test_missing_email_fails():
    with pytest.raises(ValidationError):
        DraftContract(meeting_brief="Points", client_email="")
