from collections.abc import Iterable


def split_telegram_message(text: str, max_length: int) -> Iterable[str]:
    if len(text) <= max_length:
        yield text
        return

    current = []
    current_length = 0
    for line in text.splitlines(keepends=True):
        if current_length + len(line) > max_length and current:
            yield "".join(current).strip()
            current = []
            current_length = 0

        while len(line) > max_length:
            yield line[:max_length].strip()
            line = line[max_length:]

        current.append(line)
        current_length += len(line)

    if current:
        yield "".join(current).strip()
