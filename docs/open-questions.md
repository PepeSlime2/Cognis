# Questões em aberto

Respostas podem alterar o escopo; até lá, aplicam-se os padrões registrados na especificação.

| ID | Pergunta | Padrão indicado no spec | Estado |
|---|---|---|---|
| Q1 | Aceita NetworkX como motor principal e GDS apenas para validação na F11? | Sim (D-02). | Resolvido (D-02, F5.2 — implementado em Python puro com NetworkX). |
| Q2 | Aceita SQLite além do Neo4j para estado da aplicação? | Sim (D-03). | Resolvido (D-03, F1.1 — implementado via SQLAlchemy 2 e SQLite). |
| Q3 | O sistema será de uso individual ou precisa compartilhar projetos? | Individual na v1 (D-06). | Resolvido (D-06, F1.4 — isolamento de tenant por usuário). |
| Q4 | Qual é o hardware disponível para Ollama? | CPU, timeout de 300 s. | Resolvido (D-04, F7.1 — cliente HTTP com timeout 300 s e fallback determinístico). |
| Q5 | Há repositório e board reais com atividade recente para fixtures e estudo de caso? | Usar o seed demo até existirem. | Resolvido (F5.1, F9.1 — `scripts/seed_demo.py` com 4 sprints e 6 pessoas). |
| Q6 | Qual idioma usar nos relatórios? | Somente pt-BR. | Resolvido (F8.1 a F8.5 — relatórios 100% em pt-BR em HTML, DOCX e PDF). |
