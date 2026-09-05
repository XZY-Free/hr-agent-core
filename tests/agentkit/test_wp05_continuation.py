"""WP-05 云端 continuation 续接验收：一个业务不变量。

continuation owner 以 (context_id, task_id) 隔离，并优先于「重新语义分类」：
- 同一 (context_id, task_id) 下的补充消息必须回到原 owner（local_leave / consult /
  employee_data），绝不因缺少业务关键词或语义被改判；
- 不同（同 context 的）task 互不劫持（§10.3）：task A 挂起的补充不污染 task B 的新
  分类，task B 的新分类也不改写 task A 的挂起草稿。

范围：真实 HTTPS A2A 调用（AgentKit 开发 Orchestrator 公共端点）。全部经
business_support.request_full / request_continuation / orchestrator_message /
load_identity_oracle。主体取 oracle 第一主体；无本地应用 / 模型 / 服务、无 fake-model、
无 ASGI、无 localhost、无 mock、不 skip / xfail、不打印主体 / 响应正文 / 凭据。

当前验收部署：Orchestrator v28。本文件只在头注记录取证版本，不写版本号硬断言；测试
结论由云端执行裁决。路由证据只用公共可观察的固定三值 data.route_target（local / consult
/ employee_data）与结构化 data.draft 快照，不解析 answer、不依赖 `_PROVINCE_ONLY`
判断 owner。协议 / 网络失败必须让测试直接失败（request_full / request_continuation 收敛
AcceptanceError），绝不当作预期业务拒绝。

安全：所有布尔断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle /
响应正文 / answer / 凭据；响应递归检查不含 employee_id / secret / token 字段或子串；
不 import apps / packages / veadk；不写云端、不部署、不 commit。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 固定三值路由契约；route_target 由 Orchestrator 按实际选中 RouteTarget 生成，
# 是 continuation 归属的主证据，与下游业务是否 completed 解耦。
_ROUTE_TARGETS = frozenset({"local", "consult", "employee_data"})
# Consult 远程合同公共终态（与 route_target 解耦，不因无知识正文而放行任意状态）。
_REMOTE_TERMINAL_STATUSES = ("completed", "input_required", "rejected", "failed")
# Leave 草稿 input_required 的可行领域状态（不由自然语言决定）。
_DRAFT_INPUT_REQUIRED_STATUSES = ("collecting", "ready_for_confirmation", "validation_failed")


# --------------------------------------------------------------------------
# fixtures（与 WP-01..05 一致：subject A 为 oracle 第一条主体）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    # 校验（两条主体、ref 唯一、医疗余额互异）在装入期完成，失败即整体失败。
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


# --------------------------------------------------------------------------
# 复用断言（均不打印主体 / oracle / draft 原始值 / answer / 凭据；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_truthy(answer, *, label: str) -> None:
    bs._check(isinstance(answer, str) and answer.strip(), f"{label}answer为空")


def _assert_no_sensitive(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id / secret / token 字段或子串。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            bs._check(key not in ("employee_id", "secret", "token"), f"{label}泄露敏感字段")
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, str):
        for token in ("employee_id", "secret", "token"):
            bs._check(token not in obj, f"{label}响应含敏感子串")


def _assert_route_target(res: dict, expected: str, *, label: str) -> None:
    """主路由证据：data 必须是 dict 且 data.route_target 属于固定三值，再等于期望值。

    route_target 由 Orchestrator 生成，是 continuation 归属的主证据；缺失或非三值契约
    即断言失败。绝不解析 answer 反推 owner。
    """
    inner = res.get("data")
    bs._check(isinstance(inner, dict), f"{label}data负载非 dict")
    target = inner.get("route_target")
    bs._check(target in _ROUTE_TARGETS, f"{label}route_target非固定三值")
    bs._check(target == expected, f"{label}route_target非 {expected}")


def _assert_no_draft(res: dict, *, label: str) -> None:
    """data 若为 dict 则不得出现 draft 快照（Consult / Employee Data / 澄清均无草稿）。"""
    inner = res.get("data")
    if isinstance(inner, dict):
        bs._check("draft" not in inner, f"{label}不应输出草稿快照")


def _assert_error_code_legal(res: dict, *, label: str) -> None:
    """error_code 类型合法：None 或非空字符串（不接受其它类型 / 空串 / 缺失语义）。"""
    ec = res.get("error_code")
    bs._check(ec is None or (isinstance(ec, str) and ec.strip()), f"{label}error_code类型非法")


def _assert_consult_first_input_required(res: dict, *, label: str) -> None:
    """Consult 首轮必须确实 input_required 才能证明 continuation 被登记（不放过任意终态）。"""
    bs._check(res.get("status") == "input_required", f"{label}未映射为 input_required")
    bs._check(res.get("result_type") == "missing_information", f"{label}result_type非 missing_information")
    bs._check(res.get("error_code") == "input_required", f"{label}error_code非 input_required")
    _assert_route_target(res, "consult", label=label)
    _assert_no_draft(res, label=label)
    _assert_truthy(res.get("answer"), label=label)
    _assert_no_sensitive(res, label=label)


def _assert_consult_completed(res: dict, *, label: str) -> None:
    """Consult 四川补充必须 completed（=completed / error_code 可为 not_found），拒绝其它终态。"""
    bs._check(res.get("status") == "completed", f"{label}未 completed")
    _assert_route_target(res, "consult", label=label)
    ec = res.get("error_code")
    bs._check(ec is None or ec == "not_found", f"{label}error_code非 None/not_found")
    _assert_no_draft(res, label=label)
    _assert_truthy(res.get("answer"), label=label)
    _assert_no_sensitive(res, label=label)


def _assert_consult_route(res: dict, *, label: str) -> None:
    """Consult 远程路由：route_target=consult；终态允许合同四种之一；无 draft。"""
    status = res.get("status")
    bs._check(status in _REMOTE_TERMINAL_STATUSES, f"{label}status缺失或非允许终态")
    _assert_route_target(res, "consult", label=label)
    _assert_error_code_legal(res, label=label)
    _assert_no_draft(res, label=label)
    _assert_truthy(res.get("answer"), label=label)
    _assert_no_sensitive(res, label=label)


def _draft_id_of(draft: dict, *, label: str) -> str:
    draft_id = draft.get("draft_id")
    bs._check(isinstance(draft_id, str) and draft_id, f"{label}草稿 draft_id 为空")
    return draft_id


def _revision_of(draft: dict, *, label: str) -> int:
    """revision 必须是 int 且 >= 0；type(...) is int 排除 bool（True 是 int 子类）。

    领域 Authority LeaveDraftState.revision 初始值为 0：首轮未提供任何槽位时
    revision=0 合法；续接实际推进草稿后再由调用方用单调不减 + revisions[-1] > rev0
    校验真正的增量。
    """
    revision = draft.get("revision")
    bs._check(type(revision) is int and revision >= 0, f"{label}revision 必须为非负整数(int)")
    return revision


def _assert_leave_input_required(res: dict, *, label: str) -> None:
    """Leave：input_required + route_target=local + data.draft 为 dict 且 status 属收集/确认/校验失败。"""
    bs._check(res.get("status") == "input_required", f"{label}未映射为 input_required")
    bs._check(res.get("result_type") == "missing_information", f"{label}result_type非 missing_information")
    _assert_route_target(res, "local", label=label)
    inner = res.get("data")
    draft = inner.get("draft")
    bs._check(isinstance(draft, dict), f"{label}data.draft非 dict")
    bs._check(
        draft.get("status") in _DRAFT_INPUT_REQUIRED_STATUSES,
        f"{label}draft.status非收集/确认/校验失败",
    )
    _assert_truthy(res.get("answer"), label=label)
    _assert_no_sensitive(res, label=label)


# --------------------------------------------------------------------------
# 续接结果收敛：request_continuation 区分「预期 -32602 拒绝 / 结构化结果 / 其它失败」。
# continuation 归属正确时不应被协议拒绝（owner 一致、参数合法），故这里把 -32602 拒绝
# 与其它协议/网络失败一律视为测试失败，绝不当作可接受的预期拒绝。
# --------------------------------------------------------------------------
def _drain_outcome(outcome, *, label: str):
    bs._check(not outcome.rejected, f"{label}续接被协议拒绝(-32602)")
    bs._check(outcome.category is None, f"{label}续接协议/网络失败")
    bs._check(outcome.response is not None, f"{label}续接未返回结构化结果")
    return outcome.response


# --------------------------------------------------------------------------
# 1) Consult 地区续接：新 context 首轮「育儿假政策有几天？」→ input_required/consult/无 draft；
#    同 subject、同 task/context 只发「四川」→ task id 保持、route_target=consult、无 draft、
#    且必须 completed（完成续接闭环），不转 local/Leave、不出现 draft。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_consult_region_continuation_keeps_task(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    first = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("育儿假政策有几天？", execution_subject=payload),
    )
    _assert_consult_first_input_required(first.data, label="Consult首轮")
    task_id = first.task.id
    context_id = first.task.context_id
    bs._check(isinstance(task_id, str) and task_id, "Consult首轮 task id 为空")
    bs._check(isinstance(context_id, str) and context_id, "Consult首轮 context id 为空")

    second = await bs.request_continuation(
        probes, "orchestrator",
        bs.orchestrator_message("四川", context_id=context_id, task_id=task_id, execution_subject=payload),
    )
    resp = _drain_outcome(second, label="Consult四川补充")
    bs._check(resp.task.id == task_id, "Consult四川续接 task id 未保持")
    bs._check(resp.task.context_id == context_id, "Consult四川续接 context id 未保持")
    _assert_consult_completed(resp.data, label="Consult四川补充")


# --------------------------------------------------------------------------
# 2) Leave 续接 owner：首轮「我想请假」→ input_required/local/draft；同 task/context 依次
#    「年休假」「明天下午」「改成病假」，每轮必须仍 route_target=local、同 draft_id、
#    revision 单调不减（且最终因有效更新而严格增长），不得转 consultation/employee_data，
#    状态保持 Leave 合法 input_required（不提交）。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_leave_continuation_owner_is_stable(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    first = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("我想请假", execution_subject=payload),
    )
    _assert_leave_input_required(first.data, label="Leave首轮")
    draft0 = bs.public_draft(first.data, label="Leave首轮")
    draft_id = _draft_id_of(draft0, label="Leave首轮")
    rev0 = _revision_of(draft0, label="Leave首轮")
    task_id = first.task.id
    context_id = first.task.context_id

    revisions = [rev0]
    for text in ("年休假", "明天下午", "改成病假"):
        outcome = await bs.request_continuation(
            probes, "orchestrator",
            bs.orchestrator_message(text, context_id=context_id, task_id=task_id, execution_subject=payload),
        )
        resp = _drain_outcome(outcome, label=f"Leave续接:{text}")
        bs._check(resp.task.id == task_id, f"Leave续接 task id 未保持:{text}")
        _assert_leave_input_required(resp.data, label=f"Leave续接:{text}")
        draft = bs.public_draft(resp.data, label=f"Leave续接:{text}")
        bs._check(_draft_id_of(draft, label=f"Leave续接:{text}") == draft_id,
                  f"Leave续接 draft_id 未保持:{text}")
        revision = _revision_of(draft, label=f"Leave续接:{text}")
        bs._check(revision >= revisions[-1], f"Leave续接 revision 回退:{text}")
        revisions.append(revision)

    # 三次有效更新（选假种 / 定时间 / 改假种）应让 revision 严格增长，证明草稿确实推进。
    bs._check(revisions[-1] > rev0, "Leave续接最终 revision 未因有效更新而增长")


# --------------------------------------------------------------------------
# 3) 同 context 不同 task 隔离：新 context 用「我想请假」创建 task A 并确认 local draft；
#    同 context、不带 task_id 发「公司年假制度是什么」创建 task B（task B id != task A、
#    route_target=consult、无 draft）；随后用 task A id/context 发「年休假」仍 local、同 draft_id。
#    证明 task A 挂起不劫持 task B，task B 也不改写 task A。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_same_context_different_task_isolated(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    context_id = bs.new_context()

    a = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("我想请假", context_id=context_id, execution_subject=payload),
    )
    _assert_leave_input_required(a.data, label="隔离TaskA")
    draft_a = bs.public_draft(a.data, label="隔离TaskA")
    draft_id_a = _draft_id_of(draft_a, label="隔离TaskA")
    task_a_id = a.task.id
    bs._check(a.task.context_id == context_id, "隔离TaskA context_id 不匹配")

    b = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("公司年假制度是什么", context_id=context_id, execution_subject=payload),
    )
    bs._check(b.task.id != task_a_id, "同 context 两个 task 使用了相同 task id")
    bs._check(b.task.context_id == context_id, "隔离TaskB context_id 不匹配")
    _assert_consult_route(b.data, label="隔离TaskB")

    # 用 task A id/context 补充：必须仍回到 local Leave，且是同 draft_id（未被 task B 改写）。
    a2 = await bs.request_continuation(
        probes, "orchestrator",
        bs.orchestrator_message("年休假", context_id=context_id, task_id=task_a_id, execution_subject=payload),
    )
    resp_a2 = _drain_outcome(a2, label="隔离TaskA续接")
    bs._check(resp_a2.task.id == task_a_id, "隔离TaskA续接 task id 未保持")
    _assert_leave_input_required(resp_a2.data, label="隔离TaskA续接")
    draft_a2 = bs.public_draft(resp_a2.data, label="隔离TaskA续接")
    bs._check(_draft_id_of(draft_a2, label="隔离TaskA续接") == draft_id_a,
              "隔离TaskA续接 draft_id 被 task B 改写")
