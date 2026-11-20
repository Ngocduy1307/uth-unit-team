package vn.unit.affordability.statement.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.statement.model.TransactionRecord;

import java.util.List;

@Repository
public interface TransactionRecordRepository extends JpaRepository<TransactionRecord, String> {

    List<TransactionRecord> findByAccountId(String accountId);

    List<TransactionRecord> findByDossierId(String dossierId);

    List<TransactionRecord> findByDossierIdAndClassification(String dossierId, String classification);
}
