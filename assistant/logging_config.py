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
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            record.args = self._redact_args(record.args)
        return True

    def _redact(self, value: str) -> str:
        redacted = value
        for pattern in self._patterns:
            redacted = pattern.sub("***REDACTED***", redacted)
        return redacted

    def _redact_args(self, args):
        if isinstance(args, tuple):
            return tuple(self._redact(arg) if isinstance(arg, str) else arg for arg in args)
        if isinstance(args, dict):
            return {
                key: self._redact(value) if isinstance(value, str) else value
                for key, value in args.items()
            }
        return self._redact(args) if isinstance(args, str) else args


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger().addFilter(SensitiveDataFilter())
    for handler in logging.getLogger().handlers:
        handler.addFilter(SensitiveDataFilter())
