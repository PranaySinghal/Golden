from app.errors import AppError


class StepValidationError(AppError):
    """A step can't run against the columns it would see at its point in the recipe."""

    code = "invalid_step"
    http_status = 422

    def __init__(self, message: str, step_id: str | None = None) -> None:
        super().__init__(message)
        self.step_id = step_id


class StepNotFoundError(AppError):
    code = "step_not_found"
    http_status = 404

    def __init__(self, step_id: str) -> None:
        super().__init__("That cleaning step is no longer in the recipe.")
        self.step_id = step_id


class RecipeIncompatibleError(AppError):
    code = "recipe_incompatible"
    http_status = 422

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        listed = " ".join(problems)
        super().__init__(f"This recipe doesn't fit this file. {listed}")


class RecipeFileError(AppError):
    code = "invalid_recipe_file"
    http_status = 422
