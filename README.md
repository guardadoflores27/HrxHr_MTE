# MTE Hora×Hora — Guía de Referencia Técnica

Aplicación Django para la gestión operativa de RRHH hora por hora (planeación de
producción, ejecución, y control de headcount) para MTE.

> **Estado:** Funcional en desarrollo. No lista para producción sin aplicar el
> paquete de settings de seguridad (ver sección 9). Documento generado a partir
> del código real del proyecto.

---

## 1. Stack tecnológico

| Componente | Versión / Detalle |
|---|---|
| Framework | Django 5.2.5 |
| Lenguaje | Python 3 |
| Base de datos (dev) | SQLite (`db.sqlite3`) |
| Base de datos (prod recomendada) | PostgreSQL (vía `psycopg`) |
| Servidor estáticos | WhiteNoise (`CompressedManifestStaticFilesStorage`) |
| Servidor WSGI (prod) | Gunicorn |
| Frontend | Tailwind CSS (por CDN), Font Awesome, DM Sans / JetBrains Mono |
| Zona horaria | `America/Tijuana` |

---

## 2. Estructura del proyecto

```
hrxhr_project/
├── hrxhr_project/       # Configuración raíz (settings, urls, wsgi, asgi)
├── core/                # Catálogos: WorkCenter, SubProcess, SubProcessType, Shift
├── planning/            # Planeación: DailyPlan, HourlyPlan, bloques, auditoría HC
├── production/          # Ejecución: HourlyExecution, LossReason
├── resources/           # Máquinas: WindingMachine, MachineAssignment
├── analytics/           # (vacío — reservado para reportes/KPIs)
├── users/               # Autenticación, UserProfile (roles), decoradores
├── templates/           # Plantillas globales por app
├── static/              # Estáticos del proyecto
└── manage.py
```

### Rol de cada app

- **core** — Catálogos maestros. Centros de trabajo, subprocesos, tipos de
  subproceso (con factor de conversión unidades↔piezas) y turnos.
- **planning** — El corazón del sistema. Planes diarios, desglose por hora,
  bloques operativos (lunch, pre-op, etc.) y auditoría de cambios de headcount.
- **production** — Captura de lo realmente producido por hora, scrap, y
  comentarios por situación (bajo plan, sobre plan, en meta, no productivo).
- **resources** — Máquinas de embobinado y su asignación por subproceso/fecha.
- **users** — Perfil de usuario con rol, señales de creación de perfil, y todos
  los decoradores de control de acceso por rol.
- **analytics** — Actualmente vacío. Destinado a reportes, KPIs y dashboards.

---

## 3. Modelo de datos (Base de datos actual)

### core

**WorkCenter** (Centro de trabajo)
| Campo | Tipo | Notas |
|---|---|---|
| name | CharField(100) | |
| description | TextField | opcional |
| is_active | BooleanField | default True |
| + AuditMixin | | created_by/at, updated_by/at |

**SubProcessType** (Tipo de subproceso — catálogo configurable)
| Campo | Tipo | Notas |
|---|---|---|
| name | CharField(100) | **único** |
| applies_to | CharField(choices) | `reactores` / `reactores_filtros` |
| units_per_piece | PositiveInteger | cuántas unidades = 1 pieza (factor de conversión) |
| is_active | BooleanField | default True |

**SubProcess** (Subproceso)
| Campo | Tipo | Notas |
|---|---|---|
| work_center | FK → WorkCenter | CASCADE |
| name | CharField(100) | |
| subprocess_type | FK → SubProcessType | PROTECT, actualmente **nullable** (temporal de migración) |
| + AuditMixin | | |
| `conversion_factor` | property | toma `units_per_piece` del tipo |

**Shift** (Turno)
| Campo | Tipo | Notas |
|---|---|---|
| name | CharField(100) | único |
| code | CharField(20) | único (ej. DAY, AFT, NGT) |
| start_time / end_time | TimeField | |
| is_active | BooleanField | |
| days_of_week | JSONField | lista `[0..6]`, 0=Lunes |
| `crosses_midnight` | property | detecta turnos nocturnos |

### planning

**Model** (Modelo de producto — *nombre de clase confuso, ver nota abajo*)
| Campo | Tipo | Notas |
|---|---|---|
| name | CharField(100) | único |

**DailyPlan** (Plan diario)
| Campo | Tipo | Notas |
|---|---|---|
| date | DateField | |
| work_center | FK → WorkCenter | CASCADE |
| subprocess | FK → SubProcess | CASCADE |
| headcount | IntegerField | |
| shift | FK → Shift | PROTECT, nullable |
| created_by / updated_by | FK → User | SET_NULL |
| created_by_name / updated_by_name | CharField | snapshot que sobrevive al borrado del usuario |
| **Restricción** | unique_together | `(date, subprocess, shift)` — evita planes duplicados |

**HourlyPlan** (Plan por hora)
| Campo | Tipo | Notas |
|---|---|---|
| daily_plan | FK → DailyPlan | CASCADE, related `hourly_plans` |
| hour | TimeField | |
| model | FK → Model | CASCADE |
| planned_quantity | IntegerField | |
| headcount | IntegerField | opcional, override por hora |
| is_overtime | BooleanField | |
| comments | TextField | |

**HourlyPlanBlock** (Bloque operativo — lunch, pre-op, etc.)
| Campo | Tipo | Notas |
|---|---|---|
| daily_plan | FK → DailyPlan | CASCADE, related `blocks` |
| slot_time | TimeField | hora del slot |
| block_type | CharField(choices) | lunch / preop / workfin / chair / extra |
| minutes | IntegerField | |
| reason | CharField(255) | |
| created_by | FK → User | SET_NULL |

**HeadcountAudit** (Auditoría de cambios de headcount)
| Campo | Tipo | Notas |
|---|---|---|
| daily_plan | FK → DailyPlan | CASCADE, related `hc_audits` |
| previous_value / new_value | IntegerField | |
| comment | TextField | **obligatorio** al cambiar HC |
| modified_by (+_name) | FK → User / CharField | |
| modified_at | DateTimeField | auto |

### production

**HourlyExecution** (Ejecución por hora)
| Campo | Tipo | Notas |
|---|---|---|
| hourly_plan | **OneToOne** → HourlyPlan | CASCADE |
| actual_quantity | IntegerField | default 0 |
| scrap_quantity | IntegerField | default 0 |
| comments | TextField | razón cuando quedó *bajo* plan |
| scrap_comments | TextField | comentario de scrap |
| over_comments | TextField | comentario de sobreproducción |
| ok_comments | TextField | comentario cuando está *en meta* |
| zero_comment | TextField | hora no productiva |
| `efficiency_pct` | property | actual/planned × 100 (None si planned=0) |
| `diff_quantity` | property | actual − planned |

**LossReason** (Razón de pérdida) — `name`, `is_default`
**ExecutionLossReason** — tabla puente ejecución ↔ razón de pérdida

### resources

**WindingMachine** — `name`, `is_active`
**MachineAssignment** — `subprocess` (FK), `machine` (FK), `date`

### users

**UserProfile** (extiende al User de Django, relación OneToOne)
| Campo | Tipo | Notas |
|---|---|---|
| user | OneToOne → User | CASCADE, related `profile` |
| role | CharField(choices) | `leader` / `operator` / `engineer` / `admin` (default operator) |

> Un **signal `post_save`** crea automáticamente el UserProfile al crear un User.

---

## 4. Roles de usuario

Definidos en `UserProfile.ROLE_CHOICES`:

| Rol | Código | Color UI |
|---|---|---|
| Leader | `leader` | verde esmeralda |
| Operator | `operator` | azul |
| Engineer | `engineer` | violeta |
| Admin | `admin` | rosa |

> ⚠️ **Bug conocido:** En varias partes del código (`services.py`,
> `daily_plan_delete`, etc.) se referencia un rol **`"supervisor"` que NO existe**
> en `ROLE_CHOICES`. Esto rompe funciones de borrado para todos menos admin.
> Ver sección 10.

---

## 5. Matriz de permisos por sección

Según los decoradores en `users/decorators.py`. `full` = ver + crear/editar/borrar,
`view` = solo lectura.

| Sección | Leader | Operator | Engineer | Admin |
|---|---|---|---|---|
| Dashboard | full | full | full | full |
| Planes diarios | full | view | view | full |
| Planes por hora | full | view | view | full |
| Ejecución | full | view | view | full |
| Centros de trabajo | view | view | full | full |
| Subprocesos | view | view | full | full |
| Modelos | full | view | view | full |
| Turnos | view* | view* | full | full |
| Administración de usuarios | view | view | view | full |

\* Leader y Operator pueden *usar* los turnos en planes, pero el enlace del sidebar
está oculto y no acceden a las páginas de administración de turnos.

### Decoradores disponibles

| Decorador | Permite |
|---|---|
| `@role_required(*roles)` | solo los roles indicados |
| `@admin_only` | solo admin |
| `@admin_or_leader` | admin o leader |
| `@admin_or_engineer` | admin o engineer (centros, subprocesos, turnos) |
| `@not_operator_write` | bloquea POST de operator/engineer |
| `@engineer_or_admin_write` | solo engineer/admin pueden escribir |

### Funciones de servicio para permisos (`planning/services.py`)

| Función | Roles permitidos |
|---|---|
| `can_write` | leader, admin, supervisor⚠, engineer |
| `can_move_blocks` | leader, supervisor⚠, admin |
| `can_edit_headcount` | leader, supervisor⚠, admin |
| `can_delete` | supervisor⚠, admin |

---

## 6. Mapa de rutas (URLs)

### Raíz (`hrxhr_project/urls.py`)
| Prefijo | App |
|---|---|
| `/admin/` | Django Admin |
| `/` | planning |
| `/production/` | production |
| `/core/` | core |
| `/users/` | users |

### planning (`/`)
- `/` → dashboard
- `/plans/` → lista de planes diarios (+ `/new/`, `/<pk>/edit/`, `/<pk>/delete/`)
- `/plans/<id>/hours/` → vista de plan por hora
- `/plans/<id>/api/...` → endpoints AJAX (add-row, edit-row, bloques, headcount)
- `/hours/` → tablero de planes por hora
- `/models/` → catálogo de modelos (con carga por CSV)

### production (`/production/`)
- `/production/` → lista de ejecuciones
- `/production/<plan_id>/` → captura de ejecución

### core (`/core/`)
- `/core/workcenters/` → centros de trabajo (CRUD)
- `/core/subprocess-types/` → tipos de subproceso (solo admin)
- `/core/subprocesses/` → subprocesos (CRUD)
- `/core/shifts/` → turnos (admin/engineer)

### users (`/users/`)
- `/users/login/`, `/users/logout/`, `/users/profile/`
- `/users/admin/users/` → administración de usuarios (crear/editar/borrar, solo admin)

---

## 7. Django Admin

Tras aplicar los archivos `admin.py` actualizados, hay **17 modelos** registrados:

- **core:** WorkCenter, SubProcess, SubProcessType, Shift
- **planning:** DailyPlan (con inlines de HourlyPlan y bloques), HourlyPlan,
  Model, HourlyPlanBlock (solo lectura), HeadcountAudit (solo lectura)
- **production:** HourlyExecution, LossReason, ExecutionLossReason
- **resources:** WindingMachine, MachineAssignment
- **users:** User (con UserProfile inline), UserProfile

Características: búsqueda y filtros en todos los modelos, `autocomplete_fields`
en las relaciones, tablas de auditoría en solo lectura, acción de exportar a CSV
en DailyPlan, y columnas calculadas de eficiencia/diferencia en ejecuciones.

Acceso: `http://127.0.0.1:8000/admin/` con un usuario superusuario
(`is_staff=True`).

---

## 8. Lógica de negocio clave

- **Factor de conversión unidades↔piezas:** cada `SubProcessType` define
  `units_per_piece`. La producción se captura en unidades y se convierte a piezas
  completas (`unidades // factor`, con remanente).
- **Comentarios por situación en ejecución:** al capturar producción, el sistema
  exige un comentario distinto según el resultado — bajo plan (razón de pérdida
  obligatoria), sobre plan, en meta, o hora no productiva.
- **Auditoría de headcount:** todo cambio de headcount de un plan requiere
  comentario obligatorio y queda registrado en `HeadcountAudit`.
- **Bloques operativos:** lunch, pre-op, cierre, etc. restan minutos efectivos al
  slot de la hora y pueden auto-generar el comentario de la ejecución.
- **Validación de turnos:** un plan no puede crearse para un día en que el turno
  no aplica (`days_of_week`), ni duplicar `(fecha, subproceso, turno)`.

---

## 9. Configuración y despliegue

### Estado actual (dev)
- `DEBUG = True`, `SECRET_KEY` hardcodeado, `ALLOWED_HOSTS = ['*']`, SQLite.
- **No apto para producción tal cual.**

### Comandos frecuentes
```bash
python manage.py migrate               # aplicar migraciones
python manage.py createsuperuser       # crear usuario admin
python manage.py collectstatic         # recolectar estáticos (necesario para el admin)
python manage.py runserver             # levantar servidor de desarrollo
```

> **Nota sobre estáticos:** El admin usa WhiteNoise con almacenamiento
> `Manifest`, que exige correr `collectstatic` antes de que cargue el CSS. Si
> falta, el login del admin da error 500.

### Para producción
Aplicar el paquete `settings/` (base/dev/prod) que mueve secretos a `.env` y
activa HTTPS, cookies seguras, validadores de contraseña y logging. Verificar con:
```bash
python manage.py check --deploy
```

---

## 10. Deuda técnica / pendientes conocidos

| Prioridad | Pendiente |
|---|---|
| **Crítico** | Rol `"supervisor"` fantasma referenciado pero inexistente → rompe borrados |
| **Crítico** | Settings de producción (DEBUG, SECRET_KEY, headers de seguridad) |
| Alto | Sin paginación en las listas → lento con muchos datos |
| Alto | N+1 de queries en `execution_list` y `dashboard` |
| Alto | Sin exportación a Excel/PDF |
| Medio | Apps `analytics` y `resources` sin vistas/URLs (resources solo en admin) |
| Medio | Sin tests salvo en `planning` |
| Medio | Faltan índices de BD y constraints a nivel base de datos |
| Bajo | Clase `Model` con nombre confuso (debería ser `ProductModel`) |
| Bajo | `requirements.txt` en UTF-16 (romper `pip install -r`) |

---

*Documento de referencia técnica — generado a partir del código fuente del
proyecto MTE Hora×Hora.* 7/31/2026:) -JG
