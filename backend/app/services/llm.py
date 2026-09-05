from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from app.core.logging import emit_audit_event
from app.services.llm_runtime import load_effective_llm_config

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}$")
_MAX_LOG_CHARS = 12000


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    json: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class LLMClient:
    def is_enabled(self) -> bool:
        cfg = self.runtime_config()
        return (
            bool(cfg.get('enabled'))
            and cfg.get('provider') != 'mock'
            and bool(str(cfg.get('api_key') or '').strip())
            and bool(str(cfg.get('model') or '').strip())
        )

    def runtime_config(self) -> dict[str, Any]:
        return load_effective_llm_config()

    async def chat(
        self,
        system: str,
        user: str,
        *,
        trace_context: str | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
    ) -> LLMResponse:
        cfg = self.runtime_config()
        if model_override:
            cfg = dict(cfg)
            cfg['model'] = str(model_override).strip()
        call_id = self._call_id()
        started = time.perf_counter()
        if not self.is_enabled():
            resp = self._chat_mock(system, user)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='mock',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return resp
        try:
            resp = await self._chat_compatible(cfg, system, user, max_tokens_override=max_tokens)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return resp
        except Exception as exc:
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible',
                system=system,
                user=user,
                error=str(exc),
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            raise

    def chat_sync(
        self,
        system: str,
        user: str,
        *,
        trace_context: str | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
    ) -> LLMResponse:
        cfg = self.runtime_config()
        if model_override:
            cfg = dict(cfg)
            cfg['model'] = str(model_override).strip()
        call_id = self._call_id()
        started = time.perf_counter()
        if not self.is_enabled():
            resp = self._chat_mock(system, user)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='mock',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return resp
        try:
            resp = self._chat_compatible_sync(cfg, system, user, max_tokens_override=max_tokens)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return resp
        except Exception as exc:
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible',
                system=system,
                user=user,
                error=str(exc),
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            raise

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        trace_context: str | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        cfg = self.runtime_config()
        if model_override:
            cfg = dict(cfg)
            cfg['model'] = str(model_override).strip()
        call_id = self._call_id()
        started = time.perf_counter()
        if not self.is_enabled():
            resp = self._chat_mock(system, user)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='mock_json',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return self._parse_json_response(resp)
        try:
            resp = await self._chat_compatible(cfg, system, user, json_mode=True, max_tokens_override=max_tokens)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible_json',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return self._parse_json_response(resp)
        except Exception as exc:
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible_json',
                system=system,
                user=user,
                error=str(exc),
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            raise

    def chat_json_sync(
        self,
        system: str,
        user: str,
        *,
        trace_context: str | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        cfg = self.runtime_config()
        if model_override:
            cfg = dict(cfg)
            cfg['model'] = str(model_override).strip()
        call_id = self._call_id()
        started = time.perf_counter()
        if not self.is_enabled():
            resp = self._chat_mock(system, user)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='mock_json',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return self._parse_json_response(resp)
        try:
            resp = self._chat_compatible_sync(cfg, system, user, json_mode=True, max_tokens_override=max_tokens)
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible_json',
                system=system,
                user=user,
                response=resp,
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            return self._parse_json_response(resp)
        except Exception as exc:
            self._log_call(
                call_id=call_id,
                cfg=cfg,
                mode='compatible_json',
                system=system,
                user=user,
                error=str(exc),
                duration_ms=self._duration_ms(started),
                trace_context=trace_context,
            )
            raise

    def test_connection_sync(self) -> dict[str, Any]:
        cfg = self.runtime_config()
        if not self.is_enabled():
            return {
                'ok': False,
                'message': '当前尚未启用外部模型，请先配置服务地址、访问密钥与模型名称。',
                'provider': cfg.get('provider'),
            }
        try:
            resp = self.chat_sync('你是连通性测试助手。请只输出 JSON。', '返回 JSON：{"ok": true, "reply": "测试通过"}')
            parsed = self._parse_json_response(resp)
            return {
                'ok': True,
                'provider': cfg.get('provider'),
                'model': cfg.get('model'),
                'base_url': cfg.get('base_url'),
                'sample': parsed,
            }
        except Exception as e:
            return {
                'ok': False,
                'provider': cfg.get('provider'),
                'model': cfg.get('model'),
                'base_url': cfg.get('base_url'),
                'message': str(e),
            }

    def _call_id(self) -> str:
        return f'llm-{uuid4().hex[:12]}'

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _clip(self, value: Any) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return text[:_MAX_LOG_CHARS]

    def _log_call(
        self,
        *,
        call_id: str,
        cfg: dict[str, Any],
        mode: str,
        system: str,
        user: str,
        response: LLMResponse | None = None,
        error: str | None = None,
        duration_ms: int = 0,
        trace_context: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            'event': 'model_call',
            'trace_id': call_id,
            'load_id': call_id,
            'provider': str(cfg.get('provider') or ''),
            'model': str(cfg.get('model') or ''),
            'base_url': str(cfg.get('base_url') or ''),
            'mode': mode,
            'ok': error is None,
            'duration_ms': duration_ms,
            'input': {
                'system': self._clip(system),
                'user': self._clip(user),
            },
        }
        if trace_context:
            event['trace_context'] = trace_context
        if response is not None:
            event['output'] = {
                'text': self._clip(response.text or ''),
                'json': response.json,
            }
        if error:
            event['error'] = error
        emit_audit_event(event)
        logger.info('模型调用完成，调用标识=%s，模式=%s，结果=%s，耗时=%sms', call_id, mode, '成功' if error is None else '失败', duration_ms)

    def _parse_json_response(self, resp: LLMResponse) -> dict[str, Any]:
        if resp.json is not None:
            return resp.json
        text = (resp.text or '').strip()
        if not text:
            raise LLMError('模型返回为空')
        try:
            direct = json.loads(text)
            if isinstance(direct, dict):
                return direct
        except Exception:
            pass

        match = _JSON_BLOCK_RE.search(text)
        if match:
            try:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, dict):
                    return candidate
            except Exception:
                pass

        candidates = self._extract_json_objects(text)
        if candidates:
            return self._pick_best_json_candidate(candidates)

        raise LLMError('未从模型回复中解析出结构化结果')

    def _extract_json_objects(self, text: str) -> list[dict[str, Any]]:
        in_str = False
        esc = False
        depth = 0
        start = -1
        out: list[dict[str, Any]] = []
        for i, ch in enumerate(text):
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
                continue
            if ch == '}':
                if depth <= 0:
                    continue
                depth -= 1
                if depth == 0 and start >= 0:
                    snippet = text[start : i + 1]
                    try:
                        parsed = json.loads(snippet)
                    except Exception:
                        start = -1
                        continue
                    if isinstance(parsed, dict):
                        out.append(parsed)
                    start = -1
        return out

    def _pick_best_json_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        intent_hints = [
            {"hard_skills", "soft_skills", "certificates", "experience", "preferences"},
            {"action", "args"},
            {"summary", "strengths", "gaps", "next_actions", "risk_hint"},
            {"relevance", "basic", "skills", "qualities", "potential"},
            {"summary", "markdown"},
            {"type"},
            {"ok"},
        ]

        def score(item: dict[str, Any]) -> tuple[int, int]:
            keys = set(item.keys())
            base = len(keys) * 10
            shape = 0
            for v in item.values():
                if isinstance(v, (dict, list)):
                    shape += 2
                elif isinstance(v, (str, int, float, bool)) or v is None:
                    shape += 1
            hint = 0
            for hint_set in intent_hints:
                overlap = len(keys & hint_set)
                if overlap:
                    hint += overlap * 8
            return base + shape + hint, len(keys)

        scored = [(idx, cand, *score(cand)) for idx, cand in enumerate(candidates)]
        # Prefer higher score; tie-breaker prefers later candidate because final answer usually appears later.
        scored.sort(key=lambda x: (x[2], x[3], x[0]), reverse=True)
        return scored[0][1]

    def _chat_url(self, base_url: str) -> str:
        base = (base_url or '').rstrip('/')
        if not base:
            raise LLMError('服务地址为空')
        if base.endswith('/chat/completions'):
            return base
        return f'{base}/chat/completions'

    def _headers(self, cfg: dict[str, Any]) -> dict[str, str]:
        return {
            'Authorization': f"Bearer {cfg.get('api_key')}",
            'Content-Type': 'application/json',
        }

    def _payload(
        self,
        cfg: dict[str, Any],
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens_override: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'model': cfg.get('model'),
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            'temperature': float(cfg.get('temperature') if cfg.get('temperature') is not None else 0.2),
            'stream': False,
        }
        max_tokens = int(max_tokens_override) if isinstance(max_tokens_override, int) and max_tokens_override > 0 else int(cfg.get('max_tokens') or 0)
        if max_tokens > 0:
            payload['max_tokens'] = max_tokens
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
            if str(cfg.get('provider') or '').strip().lower() == 'zhipu':
                payload['thinking'] = {'type': 'disabled'}
        return payload

    async def _chat_compatible(
        self,
        cfg: dict[str, Any],
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens_override: int | None = None,
    ) -> LLMResponse:
        url = self._chat_url(str(cfg.get('base_url') or ''))
        payload = self._payload(cfg, system, user, json_mode=json_mode, max_tokens_override=max_tokens_override)
        async with httpx.AsyncClient(timeout=float(cfg.get('timeout_seconds') or 60)) as client:
            response = await client.post(url, headers=self._headers(cfg), json=payload)
            if response.status_code >= 400:
                raise self._build_request_error(cfg, response.status_code, response.text)
            data = response.json()
        return self._parse_chat_response(data)

    def _chat_compatible_sync(
        self,
        cfg: dict[str, Any],
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens_override: int | None = None,
    ) -> LLMResponse:
        url = self._chat_url(str(cfg.get('base_url') or ''))
        payload = self._payload(cfg, system, user, json_mode=json_mode, max_tokens_override=max_tokens_override)
        with httpx.Client(timeout=float(cfg.get('timeout_seconds') or 60)) as client:
            response = client.post(url, headers=self._headers(cfg), json=payload)
            if response.status_code >= 400:
                raise self._build_request_error(cfg, response.status_code, response.text)
            data = response.json()
        return self._parse_chat_response(data)


    def _build_request_error(self, cfg: dict[str, Any], status_code: int, body: str) -> LLMError:
        provider = str(cfg.get("provider") or "").strip().lower()
        message = f"模型请求失败 {status_code}: {body}"
        if provider == "zhipu":
            message += "。请确认服务地址为 https://open.bigmodel.cn/api/paas/v4，模型名使用小写，例如 glm-4.5-air。"
        return LLMError(message)

    def _parse_chat_response(self, data: dict[str, Any]) -> LLMResponse:
        def _collect_text(value: Any) -> list[str]:
            out: list[str] = []
            if value is None:
                return out
            if isinstance(value, str):
                val = value.strip()
                if val:
                    out.append(val)
                return out
            if isinstance(value, list):
                for item in value:
                    out.extend(_collect_text(item))
                return out
            if isinstance(value, dict):
                # Compatible with OpenAI-like providers and vendor-specific variants.
                for key in ("text", "content", "output_text", "reasoning_content", "arguments"):
                    if key in value:
                        out.extend(_collect_text(value.get(key)))
                return out
            return out

        text = ''
        try:
            choice = (data.get('choices') or [{}])[0]
            message = choice.get('message') or {}
            parts = _collect_text(message.get('content'))
            if not parts:
                parts = _collect_text(message.get('reasoning_content'))

            # Function-call style response fallback.
            if not parts:
                for tc in message.get('tool_calls') or []:
                    if isinstance(tc, dict):
                        fn = tc.get('function') or {}
                        parts.extend(_collect_text(fn.get('arguments')))

            if not parts:
                parts.extend(_collect_text(data.get('output_text')))

            text = '\n'.join([part for part in parts if part]).strip()
        except Exception as exc:
            raise LLMError(f'模型返回格式异常: {data}') from exc
        parsed = None
        try:
            parsed = json.loads(text)
        except Exception:
            pass
        return LLMResponse(text=text, json=parsed, raw=data)

    def _chat_mock(self, system: str, user: str) -> LLMResponse:
        mock = {
            'note': 'mock_llm_enabled',
            'hint': '请在系统配置中填写深度求索、通义千问、豆包、智谱或其他兼容接口信息。',
        }
        return LLMResponse(text=json.dumps(mock, ensure_ascii=False), json=mock)


llm_client = LLMClient()
