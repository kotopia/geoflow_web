/* Whole-won amounts: BigInt avoids precision loss across many contracts.
 * Pure calculator, independent of DataTables and DOM; future policies belong here.
 */
(function (root) {
  'use strict';
  function calculate(rows) {
    let sum = 0n, amountCount = 0;
    for (const row of rows) {
      if (row.amount === '' || row.amount == null) continue;
      if (!/^-?\d+$/.test(String(row.amount))) throw new Error('계약금액 형식을 확인하세요.');
      sum += BigInt(row.amount); amountCount++;
    }
    const n = BigInt(amountCount), sign = sum < 0n ? -1n : 1n;
    const average = n ? sign * ((sign * sum + n / 2n) / n) : null;
    return {count: rows.length, amountCount, missing: rows.length - amountCount,
      sum: sum.toString(), average: average === null ? null : average.toString()};
  }
  root.GeoFlowAggregate = {calculate};
  if (typeof module !== 'undefined') module.exports = {calculate};
})(typeof window === 'undefined' ? globalThis : window);
