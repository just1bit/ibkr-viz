# IBKR Flex Query — 冗余字段与优化建议

## 当前 Flex Query 包含的 Sections

| Section | 大小占比(估) | 必要性 | 建议 |
|---------|------------|--------|------|
| AccountInformation | ~35% | 部分必要 | 保留（需要 accountId, accountCapabilities, acctAlias），但含大量 PII |
| EquitySummaryInBase | ~15% | **核心** | 保留（NAV, leverage 数据来源） |
| CashReport | ~25% | 必要 | 保留，但 90% 字段恒为 0 |
| OpenPositions | ~15% | **核心** | **改为 Detailed 级别**（当前 Summary 导致 cost basis 全为 0） |
| NetStockPositionSummary | ~5% | **冗余** | **取消勾选** — 与 OpenPositions 信息重复 |
| FIFOPerformanceSummaryInBase | ~2% | 可选 | 可取消（暂未使用） |
| MTMPerformanceSummaryInBase | ~2% | 可选 | 可取消（暂未使用） |
| MTDYTDPerformanceSummary | ~1% | 可选 | 可取消（暂未使用） |

## 建议操作

### 在 IBKR Client Portal → Flex Query 中：

1. **取消勾选** `NetStockPositionSummary` — 完全冗余，数据与 OpenPositions 重复
2. **取消勾选** `FIFOPerformanceSummaryInBase` — 暂未使用
3. **取消勾选** `MTMPerformanceSummaryInBase` — 暂未使用
4. **取消勾选** `MTDYTDPerformanceSummary` — 暂未使用
5. **OpenPositions → 改为 Detailed 级别** — 当前 Summary 级别导致 costBasisPrice 恒为 0，无法计算盈亏
6. **考虑添加** `MarginReport` — 当前没有 margin requirement 数据，无法计算 margin utilization

### PII 隐私注意

AccountInformation 包含以下个人信息（无法单独取消，IBKR 按 section 整包输出）：
- 邮箱：primaryEmail
- 生日：dateOfBirth
- 居住地址（含完整街道、城市、邮编）
- 这些数据存储在 S3 和 PG 中，注意访问控制

## OpenPosition 中恒为空的字段

以下字段在所有持仓中恒为空或 0，但无法在 IBKR 端单独取消（属于 OpenPositions section 的一部分）：

`accruedInt, code, commodityType, costBasisMoney, costBasisPrice, deliveryType, fifoPnlUnrealized, fineness, holdingPeriodDateTime, issuer, openDateTime, openPrice, originatingOrderID, originatingTransactionID, principalAdjustFactor, serialNumber, vestingDate, weight`

其中 `costBasisPrice=0` 和 `costBasisMoney=0` 是因为 Flex Query 设置为 Summary 级别——改为 Detailed 后可获取真实成本数据。

## EquitySummary 中恒为 0 的字段

大量资产类别子项恒为 0（bonds, commodities, crypto, funds, notes 等，含其 Long/Short 变体），约占该 section 的 60% 字段，但同样无法单独取消。

## 预期效果

取消 4 个冗余 section 后，XML 文件大小预计从 **77KB → ~55KB**（减少约 30%）。
