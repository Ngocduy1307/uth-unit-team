package vn.unit.affordability.shared.audit.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.shared.audit.model.AuditLog;

import java.util.List;

@Repository
public interface AuditLogRepository extends JpaRepository<AuditLog, String> {

    List<AuditLog> findByDossierIdOrderByCreatedAtDesc(String dossierId);

    List<AuditLog> findByEntityNameAndEntityIdOrderByCreatedAtDesc(String entityName, String entityId);
}
