# IPA Download Tool - 桌面版

基于 [ipatool](https://github.com/majd/ipatool) 的 PyQt6 图形化 iOS 应用下载工具。

## 功能特性

- 🔍 **应用搜索** - 搜索 App Store 应用
- 📥 **一键下载** - 支持 Bundle ID 和 App ID 下载
- 🎨 **现代界面** - 基于 PyQt6 的美观界面
- 💾 **下载管理** - 自定义下载路径
- 🔐 **账号管理** - 安全保存 Apple ID 凭据
- ⚙️ **配置管理** - 灵活的设置选项

## 系统要求

- **操作系统**: Windows 10/11, macOS 10.15+, Linux
- **Windows 发布版**: 无需安装 Python 与 ipatool（已内置）
- **从源码运行**: 需要 Python 3.8+；ipatool（Windows 已内置；macOS/Linux 需自行安装）
- **ipatool**: 2.1.0+（Windows 发行版内置 2.2.0）

## 安装步骤

### 1) Windows 发布版（推荐）

- 前往本项目的 Releases 页面下载 `IPA-Download-Tool.exe`
- 直接双击运行，无需安装 Python 与 ipatool（已内置）

### 2) 从源码运行（Windows/macOS/Linux）

1. 安装 Python 依赖

   ```bash
   pip install -r requirements.txt
   ```

2. 准备 ipatool

   - Windows：仓库已内置 `ipatool-2.2.0-windows-amd64.exe`，无需额外安装
   - macOS：可用 Homebrew 安装

     ```bash
     brew tap majd/repo
     brew install ipatool
     ```

     或手动下载 ipatool 二进制并放入 PATH

   - Linux：手动下载相应架构的 ipatool 二进制并放入 PATH

3. 运行程序

   ```bash
   python main.py
   ```

## 使用说明

### 首次使用

1. **登录 Apple ID**
   - 点击工具栏的"登录"按钮
   - 输入 Apple ID 邮箱
   - 输入 Apple ID 密码
   - 若启用双重认证，程序将弹窗提示，请输入设备上的 6 位验证码完成验证
   - 可选择"记住凭据"保存到本地（不建议在公共计算机勾选）

### 搜索应用

1. 切换到"🔍 搜索下载"标签页
2. 在搜索框输入应用名称或关键词
3. 点击"搜索"按钮
4. 从结果列表中选择应用，点击"下载"按钮

### 直接下载

1. 切换到"📥 直接下载"标签页
2. 输入应用的 Bundle ID（必需）或 App ID
3. 选择保存路径
4. 勾选"自动获取应用许可"（如果应用需要）
5. 点击"开始下载"按钮

### 常用应用 Bundle ID

- 微信: `com.tencent.xin`
- QQ: `com.tencent.mqq`
- 抖音: `com.ss.iphone.ugc.Aweme`
- 淘宝: `com.taobao.taobao4iphone`
- 支付宝: `com.alipay.iphoneclient`

## 配置说明

配置文件默认保存在用户目录：
- Windows: %USERPROFILE%\AppData\Local\IPADownload\config.json
- macOS/Linux: ~/.ipadownload/config.json

仓库已忽略 config.json，不会被提交；请注意保护包含账号密码的字段。

包含以下选项：

```json
{
  "apple_id": {
    "email": "your-email@example.com",
    "password": ""
  },
  "ipatool_path": "",
  "download_path": "C:\\Users\\YourName\\Downloads\\IPA",
  "auto_purchase": true,
  "remember_credentials": false
}
```

## 故障排查

### ipatool 未找到

**问题**: 提示"未找到 ipatool"

**解决**:
1. 确认已安装 ipatool
2. 将 ipatool 添加到系统 PATH
3. 或在"设置"中指定 ipatool 完整路径

### 登录失败

**问题**: 登录时提示失败

**检查**:
1. 确认 Apple ID 邮箱与密码输入正确
2. 当提示需要双重认证时，请输入设备上的 6 位验证码
3. 网络连接正常
4. 如多次失败，可在“设置-清除缓存”后重试

### 下载失败

**常见原因**:
1. 未登录 Apple ID
2. Bundle ID 不正确
3. 应用未在该地区的 App Store 上架
4. 应用需要购买但未获取许可

## 安全说明

⚠️ **重要提示**:

1. 仅下载你已购买或有权使用的应用
2. 配置文件以明文存储，注意保护；请勿将包含账号密码的 config.json 提交到版本库（已在 .gitignore 中忽略）
3. 不要在公共计算机上使用"记住凭据"功能
4. 登录可能需要双重认证，请按提示输入 6 位验证码
5. IPA 文件已加密，需要对应 Apple ID 才能安装

## 开发说明

### 项目结构

```
ipadownload/
├── main.py              # 程序入口
├── requirements.txt     # Python 依赖
├── core/                # 核心模块
│   ├── ipatool.py      # ipatool 封装
│   └── config.py       # 配置管理
└── ui/                  # 界面模块
    ├── main_window.py  # 主窗口
    ├── dialogs.py      # 对话框
    └── workers.py      # 后台线程
```

注：config.json 默认保存在用户目录（Windows: %USERPROFILE%\AppData\Local\IPADownload\config.json；macOS/Linux: ~/.ipadownload/config.json），并已在 .gitignore 中忽略。

### 打包为可执行文件

使用 PyInstaller 打包：

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包（Windows，内置 ipatool 与资源，使用本项目实际命令）
python -m PyInstaller --noconfirm --clean --windowed --onefile \
  --name "IPA-Download-Tool" \
  --icon "assets\\exe.ico" \
  --add-data "assets\\qianshu.png;assets" \
  --add-data "ipatool-2.2.0-windows-amd64.exe;." \
  main.py

# 产物：dist\\IPA-Download-Tool.exe

# 其他平台（示例）
# macOS/Linux 可按需调整图标与 add-data 语法（分隔符可能为 :）
# pyinstaller --name "IPA-Download-Tool" --windowed --onefile main.py
```

## 许可证

MIT License

## 致谢

- [ipatool](https://github.com/majd/ipatool) - 核心下载工具
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI 框架
- Apple Inc. - App Store 服务

## 支持

如有问题或建议，请提交 Issue。

⚠️ **免责声明**: 本工具仅供学习和研究使用。请遵守 Apple 的服务条款和当地法律法规。
