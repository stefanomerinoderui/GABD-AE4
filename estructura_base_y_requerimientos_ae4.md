# Resumen de Requerimientos - AE4 Gestión Avanzada de Bases de Datos

Este documento detalla los componentes técnicos y documentales que deben ser desarrollados para cumplir con la Actividad de Evaluación 4, abstrayendo el caso de negocio.

## 1. Entregables Obligatorios

Para que la entrega sea válida, el grupo debe consolidar:
*   **Informe Técnico:** Documento de texto estructurado (ver sección 3) exportado en PDF.
*   **Scripts de Base de Datos:** Archivo(s) con código ejecutable (SQL o NoSQL) debidamente comentado que permita reproducir la base de datos distribuida desde cero.
*   **Portafolio Digital (Google Drive):** Carpeta compartida donde se evidencie el proceso (borradores, esquemas lógicos, código preliminar, historial de versiones).
*   **Bitácora Individual (Moodle):** Texto de 350-550 palabras por integrante explicando su aporte, justificando decisiones técnicas con al menos dos autores (Normas APA) y enlazando a evidencias del Drive.
*   **Defensa Oral:** Coloquio individual y obligatorio de 6 minutos para validar la autoría.

## 2. Fases Técnicas de Implementación (El desarrollo práctico)

El equipo debe desplegar funcionalmente un clúster de base de datos distribuida (relacional o NoSQL) con al menos tres nodos, cumpliendo con las siguientes fases:

### Fase 1: Arquitectura de Almacenamiento Distribuido y ABM
*   **Fragmentación:** Implementar una estrategia de particionamiento (horizontal, vertical o mixta) justificada teóricamente.
*   **Replicación:** Configurar un esquema de replicación (parcial o total, síncrono o asíncrono) para garantizar la disponibilidad.
*   **Operatividad (ABM):** Proveer scripts DDL/DML que realicen el Alta, Baja y Modificación de las entidades principales, respetando la consistencia distribuida.

### Fase 2: Resiliencia y Tolerancia a Fallas
*   **Tolerancia a caídas:** Configurar y documentar qué sucede ante la caída de un nodo (procesos de conmutación / *failover*).
*   **Fundamentación Teórica:** Explicar el comportamiento del gestor de recuperación ante cortes abruptos (uso de WAL, Checkpoints, protocolos Undo/Redo).
*   **Respaldos (Backups):** Diseñar e incluir scripts para una política de copias de seguridad justificando los tiempos de recuperación esperados (RTO y RPO).

### Fase 3: Ajuste de Rendimiento (Tuning) y Analítica
*   **Indexación:** Crear índices físicos estratégicos y evaluar los planes de ejecución (ej. uso de `EXPLAIN`) para optimizar lecturas sin penalizar escrituras.
*   **Modelado Multidimensional (OLAP):** Diseñar una estructura (ej. modelo estrella o copo de nieve) para análisis de datos consolidados.
*   **Minería de Datos (KDD):** Proponer y justificar el uso de algoritmos analíticos descriptivos o predictivos aplicables a los datos del sistema.

## 3. Estructura del Informe Escrito

El documento final debe contener las siguientes secciones, combinando teoría, justificación de diseño y capturas/referencias al código práctico:

1.  **Portada:** Datos formales.
2.  **Índice:** Numerado.
3.  **Introducción:** Propósito del trabajo y contexto general de las BDD.
4.  **Conceptos Fundamentales:** Definición, ventajas, fragmentación, replicación y desafíos.
5.  **Tipos de Bases de Datos:** Comparación de motores relacionales vs. NoSQL distribuidos.
6.  **Implementación y Administración:** Pasos de configuración, monitoreo y mantenimiento.
7.  **Diseño y Modelado:** Presentación del esquema lógico de la base propuesta, estrategias de partición y demostración funcional del ABM y el clúster.
8.  **Desafíos y Tendencias:** Análisis de Teorema CAP, concurrencia, edge computing, etc.
9.  **Estudio de Caso Real:** Análisis de una empresa de la industria que utilice esta tecnología (desafíos y soluciones).
10. **Conclusiones:** Resumen de puntos clave y reflexión.
11. **Bibliografía:** Fuentes utilizadas en formato APA 7ma edición.

## 4. Criterios de Éxito Clave
*   **Reproducibilidad:** Los scripts entregados deben poder ejecutarse sin errores en cualquier máquina externa para levantar la infraestructura.
*   **Coherencia Teórica:** Las decisiones prácticas (por ejemplo, sacrificar consistencia por disponibilidad) deben estar teóricamente justificadas (Teorema CAP).
*   **Transversal:** Ortografía, redacción impecable y formato APA.