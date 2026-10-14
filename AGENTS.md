# Regras para o agente de código — COGNIS
Leia COGNIS_SPEC.md antes de agir. Idioma de UI e mensagens: pt-BR. Código e identificadores: inglês.

1. Escopo: execute SOMENTE a tarefa pedida (ex.: "F2.3"). Não refatore nem "melhore" o que não foi pedido.
2. Nunca invente endpoint, campo de API, função de biblioteca ou parâmetro. Se não tiver 100% de certeza:
   - Python: rode `python -c "import X, inspect; print(inspect.signature(X.f))"` ou `help(X.f)`.
   - GitHub/Trello: use os payloads reais em backend/tests/fixtures/ (capturados por scripts/capture_fixtures.py).
   - Outros: consulte a documentação oficial citada no SPEC §19.
3. Não altere versões de dependências existentes (package.json/package-lock.json, requirements.txt). Dependência nova: instale, depois fixe a versão instalada (pip freeze / lockfile) e registre em docs/decisions.md.
4. Métricas são calculadas em Python puro e testadas. O LLM NUNCA calcula, soma ou estima números.
5. Todo acesso a dados do grafo filtra por project_id e verifica que o projeto pertence ao usuário logado (SPEC §13).
6. Nunca logar nem retornar tokens, segredos, senhas, corpo de commits/comentários/PRs.
7. Sem dados falsos na UI: todo componente tem estado de loading, vazio e erro.
8. Antes de finalizar: `pytest -q` (backend), `npm run lint && npm run build` (frontend). Se falhar, corrija antes de responder.
9. Datas: sempre UTC tz-aware no backend/banco; exibir em America/Sao_Paulo no front.
10. Ao terminar, liste: arquivos criados/alterados, comandos rodados, o que NÃO foi feito, e itens [VERIFICAR] resolvidos.
11. Status do roadmap: ao iniciar uma tarefa Fx.y, marque-a como `em andamento` na coluna Status do roadmap em COGNIS_SPEC.md e docs/SPEC.md; ao concluir (aceite atendido e testes/lint passando), marque `feito` e adicione uma linha datada no Histórico de docs/decisions.md. Antes de começar, consulte essa coluna para saber em que ponto estamos.
