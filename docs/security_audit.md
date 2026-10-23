# Auditoria de Segurança — Checklist SPEC §13.1 (F10.1)

Este documento registra a revisão sistemática de conformidade com o checklist de segurança (MUST) definido na especificação do COGNIS (§13.1). Todos os 10 itens possuem comprovação técnica, implementação no código e cobertura por testes automatizados em `backend/tests/test_security_audit.py`.

---

| Item | Requisito do SPEC §13.1 | Status | Mecanismo de Implementação | Teste Automatizado |
|---|---|---|---|---|
| **1** | **Rotacionar segredos e `.env` fora do git** | **Conforme** | Segredos de API, JWT e Fernet gerados no `.env`. Arquivo `.env` ignorado no `.gitignore`. | `test_item1_env_file_not_tracked_in_git` |
| **2** | **Autorização por projeto (Multi-tenant)** | **Conforme** | Dependência `repository.get_project_for_user(db, pid, user_id)` aplicada em todas as rotas com `{pid}`. Rotas filhas (`/analyses/{id}`, `/reports/{id}`) resolvem o projeto no banco e exigem pertencimento ao usuário logado. Retorno estrito de **404 Not Found** (nunca 403) para evitar enumeração de recursos de outros usuários. | `test_item2_tenant_isolation_user_b_cannot_access_user_a_resources` (cobre 25 endpoints) |
| **3** | **Cypher sempre parametrizado e com `project_id`** | **Conforme** | Consultas Cypher usam `session.run()` e `tx.run()` com parâmetros nomeados (`$project_id`, `$rows`). Nenhuma query aceita interpolação de strings não sanitizadas. | `test_item3_cypher_queries_use_parameters_and_project_id` |
| **4** | **Proteção contra CSRF** | **Conforme** | Cookies de sessão usam `SameSite=Lax` e `httpOnly=True`. Middleware `validate_request_origin` em `main.py` bloqueia com **403 Forbidden** qualquer requisição não-GET sem `Origin`/`Referer` ou vinda de domínios não permitidos. | `test_item4_csrf_rejects_missing_or_unauthorized_origin` |
| **5** | **Login seguro e Rate Limiter** | **Conforme** | Limitador em memória thread-safe (`_login_attempts`) restringindo a 5 tentativas falhas/minuto por par `(IP, email)`. Retorna **429 Too Many Requests** na 6ª tentativa. Mensagem genérica `"Email ou senha inválidos"` (401). Senha mínima de 8 caracteres exigida no registro. | `test_item5_login_rate_limiter_and_password_length` |
| **6** | **Criptografia Fernet de tokens de terceiros** | **Conforme** | Tokens OAuth de GitHub e Trello armazenados cifrados com Fernet (`access_token_enc`, `refresh_token_enc`). Nunca expostos em endpoints (`/auth/me`), logs ou mensagens de erro. | `test_item6_fernet_encryption_and_no_token_leakage` |
| **7** | **Validação de entrada com Pydantic** | **Conforme** | Schemas Pydantic v2 com `extra="forbid"` em todos os corpos de requisição. Limites: nome do projeto $\le 80$ caracteres, `history_days` entre 7 e 365, máximo de 20 fontes ativas por projeto. | `test_item7_input_validation_limits` |
| **8** | **Downloads de relatório imunes a Path Traversal** | **Conforme** | O endpoint `/reports/{id}/download` recebe apenas o parâmetro tipado `format: ReportFormat` (`html`, `docx`, `pdf`). O caminho absoluto é resolvido a partir do campo `files_json` persistido no banco de dados, nunca a partir de input livre do cliente. | `test_item8_report_download_path_traversal_prevention` |
| **9** | **CORS rigoroso** | **Conforme** | `CORSMiddleware` restrito às origens declaradas em `app_config.allowed_frontend_origins` (`http://localhost:5173` e `FRONTEND_URL`), com `allow_credentials=True`. | `test_item9_cors_configuration` |
| **10** | **Higienização de logs (Minimização LGPD)** | **Conforme** | Logs registram apenas metadados (IDs de projeto, status de jobs). Tokens de acesso, credenciais, corpos de PRs e comentários nunca são logados nem persistidos. | `test_item10_log_sanitization_no_tokens_or_comment_bodies` |

---

### Execução da suíte de segurança:
```bash
pytest backend/tests/test_security_audit.py -q
# 10 passed
```
