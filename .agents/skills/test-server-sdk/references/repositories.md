# 四库定位提示

以下是曾核对的入口，不是已审查结论，也不是完整依赖清单。每次调用重新确认存在性和行号；入口移动就重新搜索，不能据此认定功能缺失。

## Android

优先搜索 `BillingManager`、`IapOrderStorage`、`Dispatcher`、`SdkLog`、`TdManager`、`SdkLoginSuccessDispatcher`；已知模块为 `bbsdk-gpbilling` 和 `bbsdk-core`。
配置生成入口：`scripts/sdkreconfig-print.js`、`scripts/sdkreconfig-kotlin.js`，通过 `packageName` 与 `sdkreconfig` 定位项目配置。继续定位广告、Adjust、Firebase 模块与实际依赖版本，不局限于这些入口。

## iOS

- `BBSDKUnity/BBSDKNativeCall.swift`
- `Modules/Core/Sources/UnityDispatcher.swift`
- `Modules/IAP/Sources/BBSDKInApp.swift`、`BBSDKIAP.swift`
- `Modules/AdMax/Sources/BBSDKAdMax.swift`
- `Modules/TA/Sources/BBSDKTA.swift`
- `Modules/Firebase/Sources/BBSDKFirebase.swift`
- `Modules/Adjust/Sources/BBSDKAdjust.swift`
- `Modules/Log/Sources/log/BBSDKS2SLogStore.swift`
- 项目配置：`scripts/sdkreconfig.js`

## SDK 服务

- IAP：`shared/iap/{deliver,deliverRetry,callback,order}.js`、`src/iap/{iap_order,http_handler_order_finish,iap_order_cp_finish}.js`
- 身份/版本：`src/login/{http_handler_login,http_handler_login2,http_handler_identity_update,user_service,versionConfig}.js`
- BI：`src/bi/bi_event_wal.js`
- 广告收入：`src/ad/ad_revenue_s2s.js`
- Firebase：`shared/firebase/measurementProtocol.js`

`versionConfig.js` 根据包配置及版本匹配，需核对实际 pgConfig 来源。相关 `.test.js` 仅作为可阅读的覆盖资料，不默认执行。

## 游戏服务

入口：`src/{glogin,gpreference,gpreferences,ccommon}.js`、`src/rank/gcommon_report.js`。继续追查数据库、发货与奖励真实写入位置。

已发现标识：`GagaSort` 按平台映射到 `igagasort` / `gpgagasort`；另有 `ColorWord`、`ColorLogic`、`wordsota` / `gpwordsota` / `iwordsota` 分支。重新检查分支可达性，不把这份列表当完整清单。

## 可选 GagaSort 客户端

仅当用户指定项目或主动纳入客户端检查时，读取 `/Users/yf/Documents/Unity/gagasort/` 中适用说明以及：

- `GagaSort/Assets/Scripts/AWFramework/SDK/BBSDK/BBSDKUtil.cs`
- `GagaSort/Assets/Scripts/AWFramework/SDK/BBSDK/SdkCallback.cs`
- `pub/iOS/Podfile`、`pub/iOS/Podfile.lock`

默认四库审查不自动变为客户端全量 QA。项目构建记录与线上部署未提供时版本映射记为未知。本地 SDK HEAD 不代表包内 SDK。
