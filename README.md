# teams-ja-zh-translator

用快捷鍵在 Microsoft Teams（或任何能打字的地方）做**中文 ↔ 日文**互譯的 Windows 小工具，背後使用 Claude。

不用再「複製 → 貼到翻譯 → 複製 → 貼回 Teams」。

| 快捷鍵 | 做什麼 |
|---|---|
| `Ctrl+Alt+J` | 把輸入框裡的中文**直接換成**商務日文（です・ます體、適度敬語），確認後按 Enter 送出 |
| `Ctrl+Alt+K` | 把**選取**的日文翻成台灣繁體中文，顯示在滑鼠旁的小視窗（Esc 關閉） |

## 需求

- Windows 10 / 11
- Python 3.10 以上
- Claude API 金鑰（在 [console.anthropic.com](https://console.anthropic.com) 申請，按用量計費）

## 安裝

1. 下載或 clone 這個 repo。
2. 雙擊 `install.bat`。它會：
   - 安裝 Python 套件（`requirements.txt`）
   - 把程式複製到 `%LOCALAPPDATA%\TeamsTranslator`
   - 在「啟動」資料夾建立捷徑，開機自動執行
   - 立即啟動
3. 第一次啟動會請你貼上 API 金鑰。

右下角系統匣的「中日」圖示可以重新設定金鑰或結束程式。

### 手動執行

```bash
pip install -r requirements.txt
python translator.py
```

## 設定

設定檔在 `%APPDATA%\TeamsTranslator\config.json`：

```json
{
  "api_key": "sk-ant-...",
  "model": "claude-opus-5-5",
  "effort": "low",
  "hotkey_reply": "ctrl+alt+j",
  "hotkey_read": "ctrl+alt+k"
}
```

- `model`：想更快、更便宜可改成 `claude-haiku-5-5`。
- `effort`：`low` 最快；想要更講究的翻譯可改成 `medium`。
- 修改後從系統匣結束程式再重新啟動即可生效。

API 金鑰只存在你自己的電腦上，翻譯內容只會送到 Anthropic API。

## 注意事項

- `Ctrl+Alt+J` 會先**全選**輸入框再翻譯，輸入框裡所有文字都會被替換。
- 如果翻譯期間你切換了視窗，日文不會被貼上，而是放在剪貼簿裡。
- 防毒軟體（例如 Norton）會攔截 HTTPS。本工具透過 [truststore](https://pypi.org/project/truststore/) 改用 Windows 憑證庫驗證，所以一般不用另外設定。
- 以系統管理員身分執行的視窗，快捷鍵可能抓不到。

## 授權

[MIT](LICENSE)
