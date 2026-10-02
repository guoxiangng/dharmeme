"""Amazon Bedrock / Claude provider, in our own AWS account.

Uses the Anthropic SDK's Bedrock client (InvokeModel under the hood) with a global
cross-region inference profile. Credentials + region come from the standard AWS
chain: the Lambda execution role in the cloud, ~/.aws locally.
"""
import os

from anthropic import AnthropicBedrock

from .base import LLMResponse

DEFAULT_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
# A meme is a template id and a few short strings, so the default cap is deliberately
# low: it bounds the cost of one visitor's call. The generator asks for more.
MAX_TOKENS = 400


class BedrockClaudeProvider:
    def __init__(self) -> None:
        # aws_region=None -> AWS_REGION / AWS_DEFAULT_REGION / ~/.aws/config.
        self.client = AnthropicBedrock(aws_region=os.environ.get("BEDROCK_REGION"))
        self.model = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL)

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> LLMResponse:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(text=text, refused=resp.stop_reason == "refusal", raw=resp)
