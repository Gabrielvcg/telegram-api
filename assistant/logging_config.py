import logging
import re


class SensitiveDataFilter(logging.Filter):
    _patterns = [
        re.compile(r"bot\d+:[A-Za-z0-9_-]+"),
        re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
        re.compile(r"github_pat_[A-Za-z0-9_]+"),
        re.compile(r"ghp_[A-Za-z0-9_]+"),
        re.compile(r"gho_[A-Za-z0-9_]+"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            record.args = tuple(self._redact(str(arg)) for arg in record.args)
        return True

    def _redact(self, value: str) -> str:
        redacted = value
        for pattern in self._patterns:
            redacted = pattern.sub("***REDACTED***", redacted)
        return redacted


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger().addFilter(SensitiveDataFilter())
    for handler in logging.getLogger().handlers:
        handler.addFilter(SensitiveDataFilter())
