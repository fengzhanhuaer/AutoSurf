# 本地图片 OCR 依赖

- `common_old.onnx` 与 `charset.json`：ddddocr 1.6.1，MIT（`LICENSE-ddddocr`）。模型来自本机已安装的官方发行包，字符表通过其默认 `DdddOcr(show_ad=False).get_charset()` 导出。默认 `beta=False/old=False` 实际加载 **common_old.onnx**，不是 common.onnx；不使用检测/滑块模型。
- `ort.wasm.min.js`、`ort-wasm-simd-threaded.mjs`、`ort-wasm-simd-threaded.wasm`：onnxruntime-web **1.23.2** 官方 npm tarball，MIT（`LICENSE-onnxruntime`）。只使用 CPU/WASM，`numThreads=1`，不使用远程脚本或模型。
- 官方来源：[ddddocr](https://github.com/sml2h3/ddddocr)、[ONNX Runtime](https://github.com/microsoft/onnxruntime/tree/v1.23.2/js/web)。所有推理在本扩展离屏页面进行，图片和答案不上传、不写存储或日志；结束关闭离屏页面释放模型。

SHA256：

| 文件 | SHA256 |
|---|---|
| common_old.onnx | b8f2ad9cbc1f2e3922a6cb9459e30824e7e2467f3fb4fd61420640e34ea0bf68 |
| charset.json | 342d871c34fd467420cd39b58a4624b505da53114e77a69b43b48b8a3ee1b24d |
| ort.wasm.min.js | c6bc9f8e1d0ecc3983a57910e6a30b2230a512bcd2e0207cd64306459c3de7b4 |
| ort-wasm-simd-threaded.mjs | 90a557d15c02bac4504d95b67f431d8594635ed2a0a62a7f2cd83d090ff91d3e |
| ort-wasm-simd-threaded.wasm | 45aee27761ad883742a8d4b8fce1538d60ce43b51adf1726fafccc59b8c1a15 |

浏览器画布高质量缩放不是 Pillow LANCZOS 的逐像素复刻。三种预处理复用旧版思路，**至少两项输出一致的六位字母数字**才允许提交（比旧版仅一项有效也可接受更保守）。一致性不是准确率保证，最终状态必须由站点确认；识别失败不自动换图或重复提交。
