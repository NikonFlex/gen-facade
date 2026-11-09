// Строка запроса к API без пустых полей (gf#356): «все разбиения» — это поле split без значения,
// а сервер принимает только train, val, test — пустое значение он отвергает.
export function query(fields) {
  return new URLSearchParams(Object.entries(fields).filter(([, v]) => v !== "" && v != null));
}
