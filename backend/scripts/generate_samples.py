"""生成样例数据：中文客服工单分类（train/val/eval）与 RAG 知识库文档。

用法（在 backend 目录下）：
    python scripts/generate_samples.py

输出到 ``backend/samples/``：
* ``tickets_train.csv`` / ``tickets_val.csv``：8 类工单意图，共 300 条，含 split 列；
* ``eval_tickets.csv``：与训练集同分布但完全独立的 120 条评测数据；
* ``knowledge_docs.jsonl``：12 篇帮助中心文档，用于 RAG 索引构建样例。

数据由模板组合生成（无外部依赖、可复现），仅用于功能演示与作品集展示。
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "samples"
SEED = 20240501

# 每个意图给出多个「问题主体 + 细节 + 诉求」片段，组合后避免重复
INTENTS: dict[str, dict[str, list[str]]] = {
    "退款退货": {
        "subjects": ["上周买的蓝牙耳机", "这个月买的连衣裙", "刚下单的空气炸锅", "前天买的机械键盘", "昨天收到的运动鞋"],
        "details": [
            "拆开发现右耳没有声音",
            "尺码偏小穿着紧",
            "内胆涂层有明显划痕",
            "键帽少了一个",
            "鞋底有开胶痕迹",
        ],
        "asks": ["想申请退款", "希望退货退款", "请问能不能直接退掉", "要走退货流程", "想换成同款新品"],
    },
    "物流查询": {
        "subjects": ["我的订单 20240512003", "快递单号 SF1234567890", "三天前下单的显示器", "预售的扫地机器人", "上周五买的床垫"],
        "details": [
            "物流信息两天没更新",
            "显示已签收但我没收到",
            "一直卡在分拣中心",
            "被改成了自提点",
            "配送时间比承诺晚了一周",
        ],
        "asks": ["想确认什么时候能到", "帮我查一下包裹位置", "能不能加急派送", "希望联系快递核实", "请给我一个准确的送达时间"],
    },
    "账号问题": {
        "subjects": ["我的会员账号", "公司统一注册的账号", "绑定的手机号", "新注册的账号", "子账号"],
        "details": [
            "突然登录不上",
            "收不到短信验证码",
            "被提示存在异地登录",
            "密码重置邮件一直没到",
            "权限被全部收回",
        ],
        "asks": ["请帮我找回账号", "想解绑旧手机号", "需要重置密码", "希望查一下登录记录", "申请恢复管理员权限"],
    },
    "发票开票": {
        "subjects": ["上个月的订单", "企业采购的 6 笔订单", "刚完成的续费", "退换货后的新订单", "本月所有消费"],
        "details": [
            "需要开增值税专用发票",
            "抬头填错了要重开",
            "电子发票一直没收到",
            "税号需要更新",
            "金额和实付对不上",
        ],
        "asks": ["请问怎么申请开票", "能不能合并开一张", "希望今天之内开出", "请发到我的邮箱", "需要红冲后重新开具"],
    },
    "商品质量": {
        "subjects": ["买的电动牙刷", "这台显示器", "入手的咖啡机", "给孩子的学习桌椅", "买的羽绒服"],
        "details": [
            "用了两周就充不进电",
            "屏幕右下角有亮点",
            "出液口漏水",
            "螺丝孔位对不上",
            "缝线处开始跑绒",
        ],
        "asks": ["这个属于质量问题吗", "能不能换新", "希望免费维修", "需要检测报告", "想投诉供应商"],
    },
    "优惠券": {
        "subjects": ["满 300 减 50 的券", "新人礼包", "直播间领的券", "会员月度券", "店铺跨店满减"],
        "details": [
            "下单时提示不可用",
            "结算后被自动取消",
            "和别的优惠不能叠加",
            "有效期比页面写的短",
            "退款后没有退回账户",
        ],
        "asks": ["想确认使用规则", "能不能补发一张", "希望手工核销", "请解释一下限制条件", "要求退还优惠券"],
    },
    "支付失败": {
        "subjects": ["刚才的订单支付", "企业网银付款", "绑定的信用卡", "花呗分期", "余额支付"],
        "details": [
            "一直提示交易失败",
            "扣款成功但订单显示未支付",
            "重复扣了两次钱",
            "提示风控拦截",
            "分期手续费和页面不一致",
        ],
        "asks": ["请帮我确认扣款状态", "希望尽快退回多扣的钱", "要怎么才能付款成功", "需要支付凭证", "想换成其他支付方式"],
    },
    "投诉建议": {
        "subjects": ["在线客服", "快递员", "售后工程师", "门店导购", "平台推荐算法"],
        "details": [
            "咨询三次都没有回复",
            "态度很不好",
            "上门检测迟到两小时",
            "强行推销延保",
            "总是推重复的商品",
        ],
        "asks": ["希望平台加强管理", "要求给出处理结果", "想要一个正式道歉", "建议增加人工入口", "希望记录这次投诉"],
    },
}

OPENINGS = ["你好，", "客服你好，", "麻烦看一下：", "咨询一下，", "您好，"]
CLOSINGS = ["谢谢。", "盼复。", "麻烦了。", "请尽快处理。", "在线等，比较急。"]

KNOWLEDGE_DOCS = [
    {
        "title": "退款政策说明",
        "source": "help/refund-policy.md",
        "text": (
            "平台支持 7 天无理由退货，商品需保持吊牌完整、不影响二次销售。"
            "生鲜、定制类、已激活的软件服务不支持无理由退货。"
            "退款将在仓库签收后 1-3 个工作日内原路退回，信用卡到账可能延迟至 7 个工作日。"
            "若商品存在质量问题，运费由平台承担，用户可在订单详情页直接发起售后申请。"
            "退款金额以实付金额为准，优惠券按规则退回账户，积分同步扣回。"
        ),
    },
    {
        "title": "物流时效与异常处理",
        "source": "help/logistics.md",
        "text": (
            "现货商品在付款后 24 小时内出库，默认使用顺丰或京东物流，偏远地区转为邮政。"
            "物流信息超过 48 小时未更新，可在订单页点击「催件」，系统会自动向承运商发起工单。"
            "显示签收但未收到货，请先联系快递员核实，超过 24 小时仍未解决可申请平台介入。"
            "预售商品以商品页公示的发货时间为准，超时未发货可申请补偿或取消订单。"
        ),
    },
    {
        "title": "账号安全与找回流程",
        "source": "help/account-security.md",
        "text": (
            "忘记密码可通过注册手机号或邮箱重置，验证码有效期为 5 分钟。"
            "连续 5 次输入错误密码会触发 30 分钟锁定，锁定期间可通过人工客服解封。"
            "检测到异地登录时系统会强制二次验证，并可一键下线所有设备。"
            "更换手机号需要先验证旧号，若旧号已停用，需提交实名信息由人工审核，审核时效为 1 个工作日。"
        ),
    },
    {
        "title": "发票开具规则",
        "source": "help/invoice.md",
        "text": (
            "订单完成后 90 天内可申请电子普通发票或增值税专用发票。"
            "专票需要提供公司名称、纳税人识别号、开户行与账号，审核通过后 3 个工作日内寄出。"
            "同一订单仅支持开具一次发票，抬头填错可在开票后 30 天内申请红冲重开。"
            "退款订单对应的发票需要先行红冲，否则无法完成退款流程。"
        ),
    },
    {
        "title": "优惠券使用限制",
        "source": "help/coupon.md",
        "text": (
            "优惠券分为店铺券、平台券与品类券，同一订单最多叠加一张平台券和一张店铺券。"
            "满减券按商品优惠后金额计算门槛，不含运费与礼品卡。"
            "优惠券不可用于虚拟商品、话费充值与企业采购专區。"
            "订单退款后优惠券在有效期内自动退回，已过期的不予补发。"
        ),
    },
    {
        "title": "支付失败常见原因",
        "source": "help/payment.md",
        "text": (
            "支付失败常见原因包括银行卡限额、余额不足、风控拦截与网络超时。"
            "若扣款成功但订单显示未支付，通常为银行侧异步通知延迟，5 分钟内会自动补单。"
            "重复扣款会在 1-3 个工作日内自动退回，也可提交支付凭证由客服加急处理。"
            "企业网银支付需在 30 分钟内完成，超时订单自动关闭。"
        ),
    },
    {
        "title": "会员权益说明",
        "source": "help/membership.md",
        "text": (
            "会员分为普通会员、银卡、金卡与黑卡，按近 12 个月消费金额自动升级。"
            "金卡及以上享受专属客服、免费上门取退与每月运费券。"
            "会员积分可用于抵扣现金，100 积分抵 1 元，单笔最多抵扣订单金额的 20%。"
            "会员有效期一年，到期后按新的消费金额重新评定等级。"
        ),
    },
    {
        "title": "售后维修与换新",
        "source": "help/after-sales.md",
        "text": (
            "整机保修一年，主要部件保修两年，人为损坏不在保修范围内。"
            "签收 15 天内出现非人为性能故障可申请换新，超过 15 天进入维修流程。"
            "维修可选择寄修或上门，寄修往返运费由平台承担。"
            "维修时长一般 3-7 个工作日，超过 15 个工作日可申请备用机或直接换新。"
        ),
    },
    {
        "title": "企业采购流程",
        "source": "help/enterprise.md",
        "text": (
            "企业采购支持对公转账、月结账期与批量议价，需先完成企业认证。"
            "单笔满 5 万元可申请专属客户经理，满 20 万元可申请账期。"
            "企业订单默认开具增值税专用发票，支持按项目拆分多张发票。"
            "批量订单支持分批发货，发货计划可在采购工作台下单时约定。"
        ),
    },
    {
        "title": "隐私与数据合规",
        "source": "help/privacy.md",
        "text": (
            "平台仅收集完成交易与服务所必需的个人信息，不会向第三方出售用户数据。"
            "用户可申请导出或删除个人数据，删除申请在 15 个工作日内完成。"
            "客服通话与在线会话会保留 6 个月用于质量抽检，涉及支付信息的片段自动脱敏。"
            "未成年人消费需监护人确认，平台提供青少年模式限制单笔金额。"
        ),
    },
    {
        "title": "价格保护规则",
        "source": "help/price-protection.md",
        "text": (
            "商品签收后 15 天内出现官方降价，可申请价格保护退还差价。"
            "价格保护不适用于限时秒杀、直播间专属价与跨店满减后的价格。"
            "申请入口在订单详情页，审核通过后差价以原支付方式退回。"
            "同一商品同一订单仅支持一次价格保护申请。"
        ),
    },
    {
        "title": "投诉与建议处理时效",
        "source": "help/complaint.md",
        "text": (
            "投诉提交后 2 小时内由专属客服首次响应，24 小时内给出处理方案。"
            "涉及服务态度的投诉会同步至服务质量管理团队并回访。"
            "对处理结果不满意可申请升级，升级由值班主管在 48 小时内复核。"
            "所有投诉记录保留一年，可作为服务改进的依据。"
        ),
    },
]


def make_ticket(rng: random.Random, intent: str) -> str:
    """按意图模板生成一条工单文本。"""
    spec = INTENTS[intent]
    subject = rng.choice(spec["subjects"])
    detail = rng.choice(spec["details"])
    ask = rng.choice(spec["asks"])
    opening = rng.choice(OPENINGS)
    closing = rng.choice(CLOSINGS)
    return f"{opening}{subject}{detail}，{ask}。{closing}"


def build_rows(count: int, rng: random.Random, start_index: int = 0) -> list[dict]:
    """生成去重后的样本行，标签在 8 个意图间均匀分布。"""
    labels = list(INTENTS.keys())
    rows: list[dict] = []
    seen: set[str] = set()
    index = start_index
    attempts = 0
    while len(rows) < count and attempts < count * 200:
        attempts += 1
        label = labels[len(rows) % len(labels)]
        text = make_ticket(rng, label)
        if text in seen:
            continue
        seen.add(text)
        rows.append({"id": index, "text": text, "label": label})
        index += 1
    if len(rows) < count:
        raise RuntimeError(f"去重后样本不足：{len(rows)}/{count}")
    return rows


def write_csv(path: Path, rows: list[dict], with_split: bool) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["text", "label", "split"] if with_split else ["text", "label"])
        for row in rows:
            if with_split:
                writer.writerow([row["text"], row["label"], row["split"]])
            else:
                writer.writerow([row["text"], row["label"]])
    print(f"已写入 {path}（{len(rows)} 行）")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    train_rows = build_rows(240, rng)
    val_rows = build_rows(60, rng, start_index=10000)
    for row in train_rows:
        row["split"] = "train"
    for row in val_rows:
        row["split"] = "val"
    write_csv(OUT_DIR / "tickets_train.csv", train_rows, with_split=True)
    write_csv(OUT_DIR / "tickets_val.csv", val_rows, with_split=True)

    eval_rows = build_rows(120, random.Random(SEED + 1), start_index=20000)
    write_csv(OUT_DIR / "eval_tickets.csv", eval_rows, with_split=False)

    with (OUT_DIR / "knowledge_docs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for doc in KNOWLEDGE_DOCS:
            handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"已写入 {OUT_DIR / 'knowledge_docs.jsonl'}（{len(KNOWLEDGE_DOCS)} 篇）")

    total = len(train_rows) + len(val_rows)
    print(f"完成：训练/验证共 {total} 条（{len(train_rows)} train + {len(val_rows)} val），评测 {len(eval_rows)} 条")


if __name__ == "__main__":
    main()
