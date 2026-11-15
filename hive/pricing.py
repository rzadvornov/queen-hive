"""Token accounting and repricing at other models' rates."""

from dataclasses import asdict, dataclass

from hive import models


@dataclass
class Tokens:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def add(self, other: "Tokens") -> "Tokens":
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        return self

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    @classmethod
    def from_usage(cls, usage: dict | None) -> "Tokens":
        """From an API usage dict (snake_case) or the CLI's ModelUsage (camelCase)."""
        usage = usage or {}

        def pick(*keys: str) -> int:
            for key in keys:
                if usage.get(key) is not None:
                    return int(usage[key])
            return 0

        return cls(
            input=pick("input_tokens", "inputTokens"),
            output=pick("output_tokens", "outputTokens"),
            cache_read=pick("cache_read_input_tokens", "cacheReadInputTokens"),
            cache_write=pick("cache_creation_input_tokens", "cacheCreationInputTokens"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


    def scaled(self, factors: "Tokens") -> "Tokens":
        """Multiply each field by the matching ratio in factors (given as floats)."""
        return Tokens(round(self.input * factors.input), round(self.output * factors.output),
                      round(self.cache_read * factors.cache_read), round(self.cache_write * factors.cache_write))


def cost(tokens: Tokens, model: models.Model, ttl: str = "1h") -> float:
    """USD for these tokens at the model's list price. ttl: cache-write duration ("1h" main session, "5m" subagent)."""
    return (
        tokens.input * model.input
        + tokens.output * model.output
        + tokens.cache_read * model.cache_read
        + tokens.cache_write * model.cache_write(ttl)
    ) / 1_000_000


def cost_by_id(tokens: Tokens, model_id: str, ttl: str = "1h") -> float | None:
    model = models.find(model_id)
    return cost(tokens, model, ttl) if model else None
