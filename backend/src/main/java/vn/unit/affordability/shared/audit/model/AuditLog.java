package vn.unit.affordability.shared.audit.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

@Entity
@Table(name = "audit_logs")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AuditLog {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "entity_name", length = 64, nullable = false)
    private String entityName;

    @Column(name = "entity_id", length = 64, nullable = false)
    private String entityId;

    @Column(name = "action", length = 32, nullable = false)
    private String action;

    @Column(name = "field_name", length = 64)
    private String fieldName;

    @Column(name = "old_value", columnDefinition = "TEXT")
    private String oldValue;

    @Column(name = "new_value", columnDefinition = "TEXT")
    private String newValue;

    @Column(name = "actor_id", length = 64, nullable = false)
    private String actorId;

    @Column(name = "actor_role", length = 32, nullable = false)
    private String actorRole;

    @Column(name = "reason", columnDefinition = "TEXT")
    private String reason;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;
}
