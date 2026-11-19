package vn.unit.affordability.statement.model;

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
import org.hibernate.annotations.UpdateTimestamp;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Entity
@Table(name = "transaction_ledger")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TransactionRecord {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "account_id", length = 36, nullable = false)
    private String accountId;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "transaction_date", nullable = false)
    private LocalDate transactionDate;

    @Column(name = "booking_date")
    private LocalDate bookingDate;

    @Column(name = "amount", precision = 18, scale = 2, nullable = false)
    private BigDecimal amount;

    @Column(name = "currency", length = 3, nullable = false)
    @Builder.Default
    private String currency = "VND";

    @Column(name = "direction", length = 10, nullable = false)
    private String direction;

    @Column(name = "running_balance", precision = 18, scale = 2)
    private BigDecimal runningBalance;

    @Column(name = "description", columnDefinition = "TEXT", nullable = false)
    private String description;

    @Column(name = "classification", length = 32, nullable = false)
    @Builder.Default
    private String classification = "UNKNOWN";

    @Column(name = "confidence_score", precision = 5, scale = 2)
    private BigDecimal confidenceScore;

    @Column(name = "is_recurring_salary")
    @Builder.Default
    private Boolean isRecurringSalary = false;

    @Column(name = "source_page")
    private Integer sourcePage;

    @Column(name = "source_row")
    private Integer sourceRow;

    @Column(name = "is_accepted", nullable = false)
    @Builder.Default
    private Boolean isAccepted = true;

    @Column(name = "exclusion_reason", length = 255)
    private String exclusionReason;

    @Column(name = "adjusted_amount", precision = 18, scale = 2)
    private BigDecimal adjustedAmount;

    @Column(name = "adjusted_by", length = 64)
    private String adjustedBy;

    @Column(name = "adjusted_at")
    private OffsetDateTime adjustedAt;

    @Column(name = "adjustment_reason", columnDefinition = "TEXT")
    private String adjustmentReason;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
