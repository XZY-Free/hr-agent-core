# 03 — Track H2：HR A2A 认证与 ExecutionSubject 身份边界

## 1. 三类身份

```text
Runtime Access Credential
≠ ExecutionSubject
≠ employeeId
```

Runtime credential证明调用权；ExecutionSubject证明代表哪个SnowHarness Principal；employeeId只在HR私有层。

## 2. Bearer Runtime Auth

Public A2A支持：
```text
none | bearer
```

bearer时额外要求：
```text
HR_ASSISTANT_A2A_BEARER_TOKEN
```

必须非空，constant-time compare。

token禁止进入log、error body、Agent Card、artifact、test snapshot。

## 3. 认证范围

无需认证：
```text
GET /health
GET /.well-known/agent-card.json
```

需要认证：
```text
JSON-RPC endpoint
```

包括message/stream、message/send、tasks/get、tasks/cancel。

## 4. execution_subject schema

最终只允许：
```text
subject_id
subject_kind
```

subject_kind必填：
```text
platform_user | platform_service
```

删除display_name，extra forbid。

## 5. metadata wire

只接受直接对象key `execution_subject`。

禁止兼容：
- `snowharness.execution_subject`；
- JSON string subject；
- tenant_id/user_id/employee_id。

旧wire直接contract_error，不做fallback parser。

## 6. PublicIdentityAdapter职责

它只是pseudonymous namespace conversion，不是authentication，不是trust。

当前硬编码 `"snowharness"` HMAC key 的“伪密钥语义”必须清除。

## 7. 固定internal_user_id算法

```text
namespace = "snowharness"
canonical = namespace + "\0" + subject_kind + "\0" + subject_id
digest = sha256(canonical)
internal_user_id = "snowharness-" + digest前32个hex
```

不用HMAC。

目的：
- 确定性；
- 不直接暴露raw subject；
- operator可离线生成mapping key；
- SnowHarness仍不知道employeeId。

## 8. Anonymous

无subject：
```text
public-anonymous
```

制度咨询可运行。

本人数据/办理由下游TrustedIdentityResolver稳定拒绝。用户正文工号不得升级成trusted identity。

## 9. 映射配置

继续复用：
```text
EMPLOYEE_IDENTITY_MAP_JSON
```

key是internal_user_id，不是raw SnowHarness subject。

新增operator-only CLI：
```text
scripts/public_subject_ref.py
```

输入subject_kind+subject_id，只输出internal_user_id，绝不接收/输出employeeId。

管理员私下配置 `internal_user_id → employeeId`。

## 10. SnowHarness永不拥有HR mapping

禁止SnowHarness保存/传employeeId、调用HR mapping API、接收raw employeeId。

## 11. Resume

每次Resume重新解析本次execution_subject。

HR不能在Resume缺subject时从旧Task偷身份。

SnowHarness按冻结合同重发same trusted subject。

## 12. Tests

必须覆盖：
- bearer missing/wrong/right；
- card/health无需bearer；
- subject_kind缺失/非法；
- display_name拒绝；
- employee_id拒绝；
- stable hash；
- user/service同id不同hash；
- anonymous；
- Resume缺subject不继承；
- Resume同subject连续；
- CLI只输出pseudonymous key。

## 13. DoD

形成：
```text
SnowHarness authenticated Principal
→ Public ExecutionSubject
→ deterministic pseudonymous HR user_id
→ HR private TrustedIdentityResolver
→ employeeId
```

SnowHarness永远看不到最后两层。
