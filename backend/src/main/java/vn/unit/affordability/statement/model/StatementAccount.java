package vn.unit.affordability.statement.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Entity
@Table(
    name = "statement_accounts",
    uniqueConstraints = {
        @UniqueConstraint(
            name = "uq_statement_accounts_dossier_bank_acc",
            columnNames = {"dossier_id", "bank_code", "account_number"}
        )
    }
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StatementAccount {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "bank_name", length = 128, nullable = false)
    private String bankName;

    @Column(name = "bank_code", length = 32, nullable = false)
    private String bankCode;

    @Column(name = "account_number", length = 64, nullable = false)
    private String accountNumber;

    @Column(name = "account_holder_name", length = 255, nullable = false)
    private String accountHolderName;

    @Column(name = "currency", length = 3, nullable = false)
    @Builder.Default
    private String currency = "VND";

    @Column(name = "statement_from_date")
    private LocalDate statementFromDate;

    @Column(name = "statement_to_date")
    private LocalDate statementToDate;

    @Column(name = "total_credit_amount", precision = 18, scale = 2)
    @Builder.Default
    private BigDecimal totalCreditAmount = BigDecimal.ZERO;

    @Column(name = "total_debit_amount", precision = 18, scale = 2)
    @Builder.Default
    private BigDecimal totalDebitAmount = BigDecimal.ZERO;

    @Column(name = "is_holder_matched")
    @Builder.Default
    private Boolean isHolderMatched = false;

    @Column(name = "match_confidence", precision = 5, scale = 2)
    private BigDecimal matchConfidence;

    @Column(name = "is_verified")
    @Builder.Default
    private Boolean isVerified = false;

    @Column(name = "verified_by", length = 64)
    private String verifiedBy;

    @Column(name = "verified_at")
    private OffsetDateTime verifiedAt;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
