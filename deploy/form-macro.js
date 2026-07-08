// 申込様式マクロ: 未記入チェックのうえ、送信用テキストを「送信用テキスト」シートに書き出す
// OnlyOffice(Desktop / Docs)専用。このファイルは自動生成
// (python -m app.services.forms)——手で直さず、様式(forms.py)を直して再生成する
// チェック定義はサーバー側の検証(parse)と同じ forms.py から生成される
(function () {
  var src = Api.GetSheet("申込書");
  var out = Api.GetSheet("送信用テキスト");
  function val(coord) {
    var v = src.GetRange(coord).GetValue();
    return v === null ? "" : String(v).trim();
  }

  // 1) 未記入チェック(正の検証はサーバー側。ここは送信前の親切)
  var issues = [];
  var required = [
    ["フリガナ", "C5"],
    ["企業・団体名", "C6"],
    ["郵便番号", "C7"],
    ["所在地", "C8"],
    ["電話番号", "C9"],
    ["フリガナ", "C11"],
    ["ご担当者名", "C12"],
    ["メールアドレス", "C13"]
  ];
  required.forEach(function (kv) {
    if (val(kv[1]) === "") issues.push("「" + kv[0] + "」が未記入です");
  });
  var atts = [
    { n: 1, f: [["氏名", "B16"], ["フリガナ", "C16"], ["所属・役職", "D16"], ["メールアドレス", "E16"], ["参加場所", "F16"]] },
    { n: 2, f: [["氏名", "B17"], ["フリガナ", "C17"], ["所属・役職", "D17"], ["メールアドレス", "E17"], ["参加場所", "F17"]] },
    { n: 3, f: [["氏名", "B18"], ["フリガナ", "C18"], ["所属・役職", "D18"], ["メールアドレス", "E18"], ["参加場所", "F18"]] }
  ];
  var entrants = 0;
  atts.forEach(function (a) {
    var vals = a.f.map(function (kv) { return val(kv[1]); });
    var any = vals.some(function (v) { return v !== ""; });
    if (!any) return;
    var missing = [];
    a.f.forEach(function (kv, i) { if (vals[i] === "") missing.push(kv[0]); });
    if (missing.length) {
      issues.push("受講者" + a.n + "人目の「" + missing.join("・") + "」が未記入です");
    } else {
      entrants++;
    }
  });
  if (entrants === 0 && issues.length === 0) {
    issues.push("受講者が1名も記入されていません");
  }
  if (issues.length) {
    out.GetRange("C5")
      .SetValue("【未記入があります。本文は作成されませんでした】");
    out.GetRange("C6").SetValue(issues.join("\n"));
    out.SetActive();
    return;
  }

  // 2) 送信用テキストの生成(1セルに一括コピー用)
  var map = [
    ["講座ID", "H1"],
    ["様式版", "H2"],
    ["発行キー", "H3"],
    ["企業名フリガナ", "C5"],
    ["企業名", "C6"],
    ["郵便番号", "C7"],
    ["所在地", "C8"],
    ["電話番号", "C9"],
    ["FAX", "C10"],
    ["担当者フリガナ", "C11"],
    ["担当者名", "C12"],
    ["メールアドレス", "C13"],
    ["受講者1", "B16"],
    ["受講者1フリガナ", "C16"],
    ["受講者1所属", "D16"],
    ["受講者1メール", "E16"],
    ["受講者1参加場所", "F16"],
    ["受講者2", "B17"],
    ["受講者2フリガナ", "C17"],
    ["受講者2所属", "D17"],
    ["受講者2メール", "E17"],
    ["受講者2参加場所", "F17"],
    ["受講者3", "B18"],
    ["受講者3フリガナ", "C18"],
    ["受講者3所属", "D18"],
    ["受講者3メール", "E18"],
    ["受講者3参加場所", "F18"]
  ];
  var lines = [];
  map.forEach(function (kv) {
    var v = val(kv[1]);
    if (v !== "") lines.push(kv[0] + ": " + v);
  });
  out.GetRange("C5").SetValue("一括コピー用(マクロ出力)");
  out.GetRange("C6").SetValue(lines.join("\n"));
  out.SetActive();
})();

