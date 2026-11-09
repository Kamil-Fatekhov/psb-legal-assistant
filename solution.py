"""Точка входа будущего сабмита команды."""

from contracts import Answer, AskRequest


def parse_question(question: str) -> AskRequest:
    """Преобразовать поле question из CSV в вопрос и историю."""
    raise NotImplementedError


def format_answer(answer: Answer) -> str:
    """Подготовить текст для колонки answer со ссылками на основания."""
    raise NotImplementedError


def main() -> None:
    """Подключить ядро и сформировать submission.csv."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
