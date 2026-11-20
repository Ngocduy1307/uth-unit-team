package vn.unit.affordability.statement.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.statement.model.StatementAccount;

import java.util.List;
import java.util.Optional;

@Repository
public interface StatementAccountRepository extends JpaRepository<StatementAccount, String> {

    List<StatementAccount> findByDossierId(String dossierId);

    Optional<StatementAccount> findByDossierIdAndBankCodeAndAccountNumber(
            String dossierId,
            String bankCode,
            String accountNumber
    );
}
