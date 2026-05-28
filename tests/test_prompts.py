from stock_news.common.llm import prompts


def test_render_prompt_messages_splits_builtin_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    (tmp_path / "classify_batch.txt").write_text(
        prompts.BUILTIN_PROMPTS["classify_batch"],
        encoding="utf-8",
    )

    messages = prompts.render_prompt_messages(
        "classify_batch",
        messages="[1] 来源: 个人消息, 发送人: 测试\n关注 A",
    )

    assert [item["role"] for item in messages] == ["system", "user"]
    assert "关注 A" not in messages[0]["content"]
    assert "关注 A" in messages[1]["content"]


def test_render_prompt_messages_preserves_custom_plain_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    (tmp_path / "classify_batch.txt").write_text(
        "自定义分类 prompt\n{messages}",
        encoding="utf-8",
    )

    messages = prompts.render_prompt_messages(
        "classify_batch",
        messages="[1] hello",
    )

    assert messages == [{"role": "user", "content": "自定义分类 prompt\n[1] hello"}]


def test_render_prompt_messages_uses_split_override(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    (tmp_path / "extract_batch.system.txt").write_text(
        "稳定抽取指令",
        encoding="utf-8",
    )
    (tmp_path / "extract_batch.user.txt").write_text(
        "动态消息：{messages}",
        encoding="utf-8",
    )

    messages = prompts.render_prompt_messages("extract_batch", messages="[1] 推荐 A")

    assert messages == [
        {"role": "system", "content": "稳定抽取指令"},
        {"role": "user", "content": "动态消息：[1] 推荐 A"},
    ]
